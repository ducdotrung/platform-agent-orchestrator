"""Transactional event admission and fenced delivery-job claims."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from platform_agent_orchestrator.contracts import EventEnvelopeV1
from platform_agent_orchestrator.core.events import DomainEvent
from platform_agent_orchestrator.runtime.execution import RunMetadata
from platform_agent_orchestrator.security import AuthorizationContext
from platform_agent_orchestrator.service_contracts import (
    ApprovalContractV1,
    ApprovalDecision,
    ApprovalDecisionRequestV1,
    DeliveryStatus,
    FeedbackContractV1,
    FeedbackRequestV1,
    PendingApprovalContractV1,
    RunContractV1,
    RunStatus,
)
from platform_agent_orchestrator.telemetry import PublicEventLogger, ServiceMetrics

from .models import (
    ApprovalRecord,
    AuditEventRecord,
    DeliveryAttemptRecord,
    DeliveryJobRecord,
    EventRecord,
    FeedbackRecord,
    IdempotencyClaimRecord,
    RunRecord,
)


class IdempotencyConflict(ValueError):
    pass


class LeaseLost(RuntimeError):
    pass


class ApprovalNotFound(LookupError):
    pass


class ApprovalConflict(ValueError):
    pass


class ApprovalExpired(ValueError):
    pass


class ApprovalStale(ValueError):
    pass


class FeedbackRunNotFound(LookupError):
    pass


@dataclass(frozen=True)
class AdmissionResult:
    run_id: str
    status: RunStatus
    duplicate: bool


@dataclass(frozen=True)
class ClaimedJob:
    job_id: str
    run_id: str
    kind: str
    lease_token: str
    attempt_number: int
    lease_expires_at: datetime


def canonical_event_bytes(envelope: EventEnvelopeV1) -> bytes:
    business_content = {
        "schema_version": envelope.schema_version,
        "type": envelope.type,
        "source": envelope.source,
        "subject": envelope.subject,
        "idempotency_key": envelope.idempotency_key,
        "payload": envelope.payload.model_dump(mode="json"),
    }
    return json.dumps(
        business_content,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def event_fingerprint(envelope: EventEnvelopeV1) -> bytes:
    return hashlib.sha256(canonical_event_bytes(envelope)).digest()


class EventRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        lease_duration: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] | None = None,
        metrics: ServiceMetrics | None = None,
        event_logger: PublicEventLogger | None = None,
    ) -> None:
        self._sessions = sessions
        self._lease_duration = lease_duration
        self._clock = clock
        self._metrics = metrics
        self._event_logger = event_logger
        self._sqlite_claim_lock = asyncio.Lock()

    async def admit_event(
        self,
        envelope: EventEnvelopeV1,
        authorization: AuthorizationContext,
        *,
        flow_name: str | None = None,
        flow_version: str = "1",
    ) -> AdmissionResult:
        fingerprint = event_fingerprint(envelope)
        selected_flow = flow_name or authorization.workflow
        try:
            result = await self._insert_admission(
                envelope,
                authorization,
                fingerprint,
                flow_name=selected_flow,
                flow_version=flow_version,
            )
        except IntegrityError as error:
            try:
                result = await self._load_duplicate(envelope, authorization, fingerprint)
            except RuntimeError:
                raise error from None
        if not result.duplicate:
            self._run_transition(RunStatus.QUEUED.value)
        return result

    async def _insert_admission(
        self,
        envelope: EventEnvelopeV1,
        authorization: AuthorizationContext,
        fingerprint: bytes,
        *,
        flow_name: str,
        flow_version: str,
    ) -> AdmissionResult:
        async with self._sessions() as session, session.begin():
            existing = await self._find_event(session, envelope, authorization.scope_id)
            if existing is not None:
                return await self._duplicate_result(session, existing, fingerprint)

            run_id = str(uuid4())
            job_id = str(uuid4())
            event = EventRecord(
                id=envelope.id,
                scope_id=authorization.scope_id,
                source=envelope.source,
                event_type=envelope.type,
                schema_version=envelope.schema_version,
                subject=envelope.subject,
                occurred_at=envelope.occurred_at,
                correlation_id=envelope.correlation_id,
                idempotency_key=envelope.idempotency_key,
                fingerprint=fingerprint,
                payload=envelope.payload.model_dump(mode="json"),
            )
            session.add(event)
            # The classical mappings intentionally expose no relationship objects.
            # Flush each new FK parent before its dependants so ordering does not rely
            # on SQLite's default foreign-key behavior or ORM relationship metadata.
            await session.flush()

            run = RunRecord(
                id=run_id,
                scope_id=authorization.scope_id,
                event_id=envelope.id,
                workflow=flow_name,
                workflow_contract_version=flow_version,
                thread_id=run_id,
                status=RunStatus.QUEUED.value,
            )
            session.add(run)
            await session.flush()

            now = await self._now(session)
            session.add(
                DeliveryJobRecord(
                    id=job_id,
                    scope_id=authorization.scope_id,
                    run_id=run_id,
                    kind="invoke",
                    operation_key="initial",
                    status=DeliveryStatus.PENDING.value,
                    available_at=now,
                )
            )
            session.add(
                AuditEventRecord(
                    scope_id=authorization.scope_id,
                    actor_type=authorization.actor_type,
                    actor_id=authorization.actor_id,
                    action="event.admit",
                    outcome="accepted",
                    reason_code="new_event",
                    event_id=envelope.id,
                    run_id=run_id,
                    job_id=job_id,
                    request_id=envelope.correlation_id,
                    correlation_id=envelope.correlation_id,
                    new_state=RunStatus.QUEUED.value,
                    action_hash=fingerprint,
                    metadata_json={"policy_version": authorization.policy_version},
                )
            )
            await session.flush()
            return AdmissionResult(run_id, RunStatus.QUEUED, duplicate=False)

    async def _load_duplicate(
        self,
        envelope: EventEnvelopeV1,
        authorization: AuthorizationContext,
        fingerprint: bytes,
    ) -> AdmissionResult:
        async with self._sessions() as session:
            existing = await self._find_event(session, envelope, authorization.scope_id)
            if existing is None:
                raise RuntimeError("admission conflict rolled back without an existing event")
            return await self._duplicate_result(session, existing, fingerprint)

    @staticmethod
    async def _find_event(
        session: AsyncSession,
        envelope: EventEnvelopeV1,
        scope_id: str,
    ) -> EventRecord | None:
        return await session.scalar(
            sa.select(EventRecord).where(
                EventRecord.scope_id == scope_id,
                EventRecord.source == envelope.source,
                EventRecord.idempotency_key == envelope.idempotency_key,
            )
        )

    @staticmethod
    async def _duplicate_result(
        session: AsyncSession,
        event: EventRecord,
        fingerprint: bytes,
    ) -> AdmissionResult:
        if event.fingerprint != fingerprint:
            raise IdempotencyConflict("idempotency key was reused with changed content")
        run = await session.scalar(
            sa.select(RunRecord).where(
                RunRecord.event_id == event.id,
                RunRecord.replay_of_run_id.is_(None),
            )
        )
        if run is None:
            raise RuntimeError("accepted event has no initial run")
        return AdmissionResult(run.id, RunStatus(run.status), duplicate=True)

    async def claim_jobs(self, worker_id: str, *, limit: int = 1) -> list[ClaimedJob]:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1 to 128 characters")
        if not 1 <= limit <= 32:
            raise ValueError("claim limit must be between 1 and 32")

        async with self._sessions() as probe:
            dialect = probe.bind.dialect.name if probe.bind is not None else "unknown"
        if dialect == "sqlite":
            async with self._sqlite_claim_lock:
                claims = await self._claim_jobs(worker_id, limit=limit)
        else:
            claims = await self._claim_jobs(worker_id, limit=limit)
        try:
            if self._metrics is not None:
                self._metrics.delivery_claims.labels("claimed").inc(len(claims))
        except Exception:
            pass
        return claims

    async def get_run(self, run_id: str, scope_id: str) -> RunContractV1 | None:
        async with self._sessions() as session:
            run = await session.scalar(
                sa.select(RunRecord).where(
                    RunRecord.id == run_id,
                    RunRecord.scope_id == scope_id,
                )
            )
            if run is None:
                return None
            return RunContractV1(
                run_id=run.id,
                event_id=run.event_id,
                scope_id=run.scope_id,
                thread_id=run.thread_id,
                workflow=run.workflow,
                workflow_contract_version=run.workflow_contract_version,
                status=RunStatus(run.status),
                result_summary=run.result_summary,
                created_at=run.created_at,
                started_at=run.started_at,
                interrupted_at=run.interrupted_at,
                finished_at=run.finished_at,
                version=run.version,
            )

    async def load_claimed_event(self, claim: ClaimedJob) -> DomainEvent:
        async with self._sessions() as session:
            job = await session.scalar(
                sa.select(DeliveryJobRecord).where(
                    DeliveryJobRecord.id == claim.job_id,
                    DeliveryJobRecord.run_id == claim.run_id,
                    DeliveryJobRecord.status == DeliveryStatus.LEASED.value,
                    DeliveryJobRecord.lease_token == claim.lease_token,
                )
            )
            if job is None:
                raise LeaseLost("delivery lease is no longer active")
            run = await session.get(RunRecord, claim.run_id)
            if run is None:
                raise RuntimeError("claimed run is missing")
            event = await session.get(EventRecord, run.event_id)
            if event is None:
                raise RuntimeError("claimed event is missing")
            return DomainEvent(
                id=event.id,
                type=event.event_type,
                source=event.source,
                subject=event.subject,
                occurred_at=event.occurred_at,
                correlation_id=event.correlation_id,
                idempotency_key=event.idempotency_key,
                tenant_id=run.scope_id,
                data=event.payload,
            )

    async def load_claimed_run(self, claim: ClaimedJob) -> RunMetadata:
        """Reconstruct runtime-neutral identity while enforcing the active lease."""

        async with self._sessions() as session:
            job = await session.scalar(
                sa.select(DeliveryJobRecord).where(
                    DeliveryJobRecord.id == claim.job_id,
                    DeliveryJobRecord.run_id == claim.run_id,
                    DeliveryJobRecord.status == DeliveryStatus.LEASED.value,
                    DeliveryJobRecord.lease_token == claim.lease_token,
                )
            )
            if job is None:
                raise LeaseLost("delivery lease is no longer active")
            run = await session.get(RunRecord, claim.run_id)
            if run is None:
                raise RuntimeError("claimed run is missing")
            event = await session.get(EventRecord, run.event_id)
            if event is None:
                raise RuntimeError("claimed event is missing")
            return self._run_metadata(run, event)

    async def get_run_metadata(
        self,
        run_id: str,
        tenant_id: str,
    ) -> RunMetadata | None:
        """Load durable resume identity without loading checkpoints or flow objects."""

        async with self._sessions() as session:
            run = await session.scalar(
                sa.select(RunRecord).where(
                    RunRecord.id == run_id,
                    RunRecord.scope_id == tenant_id,
                )
            )
            if run is None:
                return None
            event = await session.get(EventRecord, run.event_id)
            if event is None:
                raise RuntimeError("durable run event is missing")
            return self._run_metadata(run, event)

    @staticmethod
    def _run_metadata(run: RunRecord, event: EventRecord) -> RunMetadata:
        return RunMetadata(
            run_id=run.id,
            flow_name=run.workflow,
            flow_version=run.workflow_contract_version,
            thread_id=run.thread_id,
            correlation_id=event.correlation_id,
            tenant_id=run.scope_id,
            status=run.status,
        )

    async def load_claimed_resume(self, claim: ClaimedJob) -> dict[str, Any]:
        if claim.kind != "resume":
            raise ValueError("resume payload requires a resume job")
        async with self._sessions() as session:
            job = await session.scalar(
                sa.select(DeliveryJobRecord).where(
                    DeliveryJobRecord.id == claim.job_id,
                    DeliveryJobRecord.run_id == claim.run_id,
                    DeliveryJobRecord.kind == "resume",
                    DeliveryJobRecord.status == DeliveryStatus.LEASED.value,
                    DeliveryJobRecord.lease_token == claim.lease_token,
                )
            )
            if job is None:
                raise LeaseLost("resume lease is no longer active")
            approval_id = job.operation_key.removeprefix("approval:")
            approval = await session.get(ApprovalRecord, approval_id)
            if approval is None or approval.decision != ApprovalDecision.APPROVED.value:
                raise RuntimeError("resume job has no approved decision")
            return {
                "approved": True,
                "actor": approval.actor_id,
                "reason": approval.reason,
            }

    async def list_pending_approvals(
        self, scope_id: str
    ) -> list[PendingApprovalContractV1]:
        async with self._sessions() as session:
            runs = list(
                (
                    await session.scalars(
                        sa.select(RunRecord)
                        .where(
                            RunRecord.scope_id == scope_id,
                            RunRecord.status == RunStatus.WAITING_APPROVAL.value,
                        )
                        .order_by(RunRecord.interrupted_at, RunRecord.id)
                        .limit(100)
                    )
                ).all()
            )
            return [self._pending_approval(run) for run in runs]

    async def decide_approval(
        self,
        run_id: str,
        request: ApprovalDecisionRequestV1,
        authorization: Any,
    ) -> ApprovalContractV1:
        request_fingerprint = hashlib.sha256(
            request.model_dump_json(exclude={"idempotency_key"}).encode()
        ).digest()
        async with self._sessions() as session, session.begin():
            now = await self._now(session)
            run = await session.scalar(
                sa.select(RunRecord)
                .where(RunRecord.id == run_id, RunRecord.scope_id == authorization.scope_id)
                .with_for_update()
            )
            if run is None:
                raise ApprovalNotFound("approval run was not found")
            if run.status != RunStatus.WAITING_APPROVAL.value:
                raise ApprovalConflict("run is not waiting for approval")
            pending = self._pending_approval(run)
            if request.run_version != run.version:
                raise ApprovalStale("run version changed")
            if request.approval_version != pending.approval_version:
                raise ApprovalStale("approval version changed")
            if request.action_hash != pending.action_hash:
                raise ApprovalConflict("approved action hash changed")
            expires_at = pending.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if now > expires_at:
                raise ApprovalExpired("approval request expired")
            existing = await session.scalar(
                sa.select(ApprovalRecord).where(
                    ApprovalRecord.run_id == run.id,
                    ApprovalRecord.approval_version == request.approval_version,
                )
            )
            if existing is not None:
                raise ApprovalConflict("approval was already decided")
            reused_key = await session.scalar(
                sa.select(IdempotencyClaimRecord).where(
                    IdempotencyClaimRecord.scope_id == authorization.scope_id,
                    IdempotencyClaimRecord.boundary == "approval",
                    IdempotencyClaimRecord.idempotency_key == request.idempotency_key,
                )
            )
            if reused_key is not None:
                raise ApprovalConflict("approval idempotency key was already used")

            claim_id = str(uuid4())
            approval_id = str(uuid4())
            session.add(
                IdempotencyClaimRecord(
                    id=claim_id,
                    scope_id=authorization.scope_id,
                    boundary="approval",
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                    status="succeeded",
                    resource_kind="approval",
                    resource_id=approval_id,
                    response_status=202,
                    response_summary=request.decision.value,
                    created_at=now,
                    completed_at=now,
                    expires_at=now + timedelta(days=30),
                )
            )
            await session.flush()

            approval = ApprovalRecord(
                id=approval_id,
                scope_id=authorization.scope_id,
                run_id=run.id,
                approval_version=request.approval_version,
                decision=request.decision.value,
                actor_id=authorization.actor_id,
                actor_type=authorization.actor_type,
                reason=request.reason,
                action_hash=bytes.fromhex(request.action_hash),
                policy_version=authorization.policy_version,
                decided_at=now,
                expires_at=expires_at,
                idempotency_claim_id=claim_id,
            )
            session.add(approval)
            await session.flush()

            prior_state = run.status
            if request.decision == ApprovalDecision.APPROVED:
                session.add(
                    DeliveryJobRecord(
                        id=str(uuid4()),
                        scope_id=run.scope_id,
                        run_id=run.id,
                        kind="resume",
                        operation_key=f"approval:{approval_id}",
                        status=DeliveryStatus.PENDING.value,
                        available_at=now,
                    )
                )
                run.status = RunStatus.QUEUED.value
                run.result_summary = json.dumps(
                    {"status": "approved", "approval_id": approval_id},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            else:
                run.status = RunStatus.REJECTED.value
                run.result_summary = json.dumps(
                    {"status": "rejected", "approval_id": approval_id},
                    separators=(",", ":"),
                    sort_keys=True,
                )
                run.finished_at = now
            run.version += 1
            session.add(
                AuditEventRecord(
                    scope_id=run.scope_id,
                    actor_type=authorization.actor_type,
                    actor_id=authorization.actor_id,
                    action="approval.decide",
                    outcome=request.decision.value,
                    reason_code="reviewer_decision",
                    run_id=run.id,
                    approval_id=approval_id,
                    prior_state=prior_state,
                    new_state=run.status,
                    action_hash=approval.action_hash,
                    metadata_json={"approval_version": request.approval_version},
                )
            )
            await session.flush()
            contract = ApprovalContractV1(
                approval_id=approval.id,
                run_id=approval.run_id,
                approval_version=approval.approval_version,
                decision=ApprovalDecision(approval.decision),
                actor_id=approval.actor_id,
                actor_type=approval.actor_type,
                reason=approval.reason,
                action_hash=approval.action_hash.hex(),
                policy_version=approval.policy_version,
                decided_at=approval.decided_at,
                expires_at=approval.expires_at,
            )
        try:
            if self._metrics is not None:
                self._metrics.approval_decisions.labels(request.decision.value).inc()
        except Exception:
            pass
        new_status = (
            RunStatus.QUEUED.value
            if request.decision == ApprovalDecision.APPROVED
            else RunStatus.REJECTED.value
        )
        self._run_transition(new_status)
        return contract

    @staticmethod
    def _pending_approval(run: RunRecord) -> PendingApprovalContractV1:
        try:
            summary = json.loads(run.result_summary or "")
            pending = summary["approval"]
            return PendingApprovalContractV1(
                run_id=run.id,
                approval_version=pending["approval_version"],
                kind=pending["kind"],
                action_hash=pending["action_hash"],
                expires_at=pending["expires_at"],
                run_version=run.version,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("waiting run has invalid approval metadata") from error

    async def ingest_feedback(
        self,
        run_id: str,
        request: FeedbackRequestV1,
        authorization: Any,
    ) -> FeedbackContractV1:
        async with self._sessions() as session, session.begin():
            run = await session.scalar(
                sa.select(RunRecord).where(
                    RunRecord.id == run_id,
                    RunRecord.scope_id == authorization.scope_id,
                )
            )
            if run is None:
                raise FeedbackRunNotFound("feedback run was not found")
            now = await self._now(session)
            feedback_id = str(uuid4())
            session.add(
                FeedbackRecord(
                    id=feedback_id,
                    scope_id=authorization.scope_id,
                    run_id=run.id,
                    actor_id=authorization.actor_id,
                    actor_type=authorization.actor_type,
                    rating=request.rating.value,
                    reason=request.reason,
                    trace_id=request.trace_id,
                    created_at=now,
                    retention_until=now + timedelta(days=90),
                    metadata_json=request.metadata,
                )
            )
            session.add(
                AuditEventRecord(
                    scope_id=run.scope_id,
                    actor_type=authorization.actor_type,
                    actor_id=authorization.actor_id,
                    action="feedback.create",
                    outcome="recorded",
                    reason_code=request.rating.value,
                    run_id=run.id,
                    new_state=run.status,
                    metadata_json={"feedback_id": feedback_id},
                )
            )
            await session.flush()
            contract = FeedbackContractV1(
                feedback_id=feedback_id,
                run_id=run.id,
                actor_id=authorization.actor_id,
                rating=request.rating,
                reason=request.reason,
                trace_id=request.trace_id,
                created_at=now,
                metadata=request.metadata,
            )
        try:
            if self._metrics is not None:
                self._metrics.feedback_records.labels(request.rating.value).inc()
        except Exception:
            pass
        return contract

    async def record_success(self, claim: ClaimedJob, summary: str) -> None:
        await self._record_outcome(
            claim,
            job_status=DeliveryStatus.COMPLETED,
            run_status=RunStatus.SUCCEEDED,
            outcome="succeeded",
            summary=summary,
            terminal=True,
        )

    async def record_interruption(self, claim: ClaimedJob, summary: str) -> None:
        await self._record_outcome(
            claim,
            job_status=DeliveryStatus.COMPLETED,
            run_status=RunStatus.WAITING_APPROVAL,
            outcome="interrupted",
            summary=summary,
            interrupted=True,
        )

    async def record_retry(
        self,
        claim: ClaimedJob,
        *,
        category: str,
        fingerprint: bytes,
        available_at: datetime,
    ) -> None:
        await self._record_outcome(
            claim,
            job_status=DeliveryStatus.RETRY_WAIT,
            run_status=RunStatus.RETRY_WAIT,
            outcome="retryable_failure",
            error_category=category,
            error_fingerprint=fingerprint,
            available_at=available_at,
        )

    async def record_terminal_failure(
        self,
        claim: ClaimedJob,
        *,
        category: str,
        fingerprint: bytes,
    ) -> None:
        await self._record_outcome(
            claim,
            job_status=DeliveryStatus.FAILED_TERMINAL,
            run_status=RunStatus.FAILED_TERMINAL,
            outcome="terminal_failure",
            error_category=category,
            error_fingerprint=fingerprint,
            terminal=True,
        )

    async def _record_outcome(
        self,
        claim: ClaimedJob,
        *,
        job_status: DeliveryStatus,
        run_status: RunStatus,
        outcome: str,
        summary: str | None = None,
        error_category: str | None = None,
        error_fingerprint: bytes | None = None,
        available_at: datetime | None = None,
        terminal: bool = False,
        interrupted: bool = False,
    ) -> None:
        if summary is not None and len(summary) > 16_384:
            raise ValueError("run summary exceeds 16 KiB")
        if error_fingerprint is not None and len(error_fingerprint) != 32:
            raise ValueError("error fingerprint must be 32 bytes")
        async with self._sessions() as session, session.begin():
            now = await self._now(session)
            job = await session.scalar(
                sa.select(DeliveryJobRecord)
                .where(
                    DeliveryJobRecord.id == claim.job_id,
                    DeliveryJobRecord.status == DeliveryStatus.LEASED.value,
                    DeliveryJobRecord.lease_token == claim.lease_token,
                )
                .with_for_update()
            )
            if job is None:
                raise LeaseLost("delivery outcome lost its lease fence")
            attempt = await session.scalar(
                sa.select(DeliveryAttemptRecord).where(
                    DeliveryAttemptRecord.job_id == claim.job_id,
                    DeliveryAttemptRecord.lease_token == claim.lease_token,
                    DeliveryAttemptRecord.finished_at.is_(None),
                )
            )
            if attempt is None:
                raise LeaseLost("delivery outcome has no active attempt")
            run = await session.get(RunRecord, claim.run_id)
            if run is None:
                raise RuntimeError("delivery outcome has no run")

            lease_owner = job.lease_owner or "worker"
            job.status = job_status.value
            job.lease_token = None
            job.lease_owner = None
            job.lease_expires_at = None
            job.last_heartbeat_at = None
            job.last_error_category = error_category
            job.last_error_fingerprint = error_fingerprint
            job.available_at = available_at or job.available_at
            job.completed_at = now if job_status == DeliveryStatus.COMPLETED or terminal else None
            job.version += 1
            attempt.finished_at = now
            attempt.outcome = outcome
            attempt.error_category = error_category
            attempt.error_fingerprint = error_fingerprint
            attempt.retry_available_at = available_at
            attempt.version += 1
            run.status = run_status.value
            run.result_summary = summary
            run.error_category = error_category
            run.error_fingerprint = error_fingerprint
            run.interrupted_at = now if interrupted else run.interrupted_at
            run.finished_at = now if terminal else None
            run.version += 1
            session.add(
                AuditEventRecord(
                    scope_id=job.scope_id,
                    actor_type="service",
                    actor_id=lease_owner,
                    action="delivery.outcome",
                    outcome=outcome,
                    reason_code=error_category or outcome,
                    run_id=run.id,
                    job_id=job.id,
                    prior_state=DeliveryStatus.LEASED.value,
                    new_state=job_status.value,
                    action_hash=error_fingerprint,
                    metadata_json={"attempt_number": attempt.attempt_number},
                )
            )
            await session.flush()
        self._run_transition(run_status.value)

    async def _claim_jobs(self, worker_id: str, *, limit: int) -> list[ClaimedJob]:
        async with self._sessions() as session, session.begin():
            now = await self._now(session)
            eligible = sa.or_(
                sa.and_(
                    DeliveryJobRecord.status.in_(("pending", "retry_wait")),
                    DeliveryJobRecord.available_at <= now,
                ),
                sa.and_(
                    DeliveryJobRecord.status == "leased",
                    DeliveryJobRecord.lease_expires_at <= now,
                ),
            )
            statement = (
                sa.select(DeliveryJobRecord)
                .where(eligible, DeliveryJobRecord.attempt_count < DeliveryJobRecord.max_attempts)
                .order_by(
                    DeliveryJobRecord.available_at,
                    DeliveryJobRecord.created_at,
                    DeliveryJobRecord.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            jobs = list((await session.scalars(statement)).all())
            claims: list[ClaimedJob] = []
            for job in jobs:
                prior_status = job.status
                if job.status == DeliveryStatus.LEASED.value:
                    active_attempt = await session.scalar(
                        sa.select(DeliveryAttemptRecord).where(
                            DeliveryAttemptRecord.job_id == job.id,
                            DeliveryAttemptRecord.finished_at.is_(None),
                        )
                    )
                    if active_attempt is not None:
                        active_attempt.finished_at = now
                        active_attempt.outcome = "worker_lost"
                        active_attempt.error_category = "worker_lost"
                        active_attempt.version += 1

                token = str(uuid4())
                job.status = DeliveryStatus.LEASED.value
                job.lease_token = token
                job.lease_owner = worker_id
                job.lease_expires_at = now + self._lease_duration
                job.last_heartbeat_at = now
                job.attempt_count += 1
                job.version += 1
                attempt = DeliveryAttemptRecord(
                    id=str(uuid4()),
                    job_id=job.id,
                    attempt_number=job.attempt_count,
                    lease_token=token,
                    worker_id=worker_id,
                    started_at=now,
                    last_heartbeat_at=now,
                )
                session.add(attempt)
                run = await session.get(RunRecord, job.run_id)
                if run is None:
                    raise RuntimeError("delivery job has no run")
                run.status = RunStatus.RUNNING.value
                run.started_at = run.started_at or now
                run.version += 1
                session.add(
                    AuditEventRecord(
                        scope_id=job.scope_id,
                        actor_type="service",
                        actor_id=worker_id,
                        action="delivery.claim",
                        outcome="leased",
                        reason_code="job_due",
                        run_id=job.run_id,
                        job_id=job.id,
                        prior_state=prior_status,
                        new_state="leased",
                        metadata_json={"attempt_number": job.attempt_count},
                    )
                )
                claims.append(
                    ClaimedJob(
                        job_id=job.id,
                        run_id=job.run_id,
                        kind=job.kind,
                        lease_token=token,
                        attempt_number=job.attempt_count,
                        lease_expires_at=job.lease_expires_at,
                    )
                )
            await session.flush()
            return claims

    async def _now(self, session: AsyncSession) -> datetime:
        if self._clock is not None:
            now = self._clock()
        else:
            now = await session.scalar(sa.select(sa.func.now()))
            if now is None:
                raise RuntimeError("database did not return a transaction timestamp")
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now

    def _run_transition(self, status: str) -> None:
        try:
            if self._metrics is not None:
                self._metrics.run_transitions.labels(status).inc()
            if self._event_logger is not None:
                self._event_logger.info("run_transition", status=status, workflow="alert")
        except Exception:
            pass
