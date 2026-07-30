"""Transactional event admission and fenced delivery-job claims."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from platform_agent_orchestrator.contracts import EventEnvelopeV1
from platform_agent_orchestrator.security import AuthorizationContext
from platform_agent_orchestrator.service_contracts import (
    DeliveryStatus,
    RunContractV1,
    RunStatus,
)

from .models import (
    AuditEventRecord,
    DeliveryAttemptRecord,
    DeliveryJobRecord,
    EventRecord,
    RunRecord,
)


class IdempotencyConflict(ValueError):
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
    ) -> None:
        self._sessions = sessions
        self._lease_duration = lease_duration
        self._clock = clock
        self._sqlite_claim_lock = asyncio.Lock()

    async def admit_event(
        self,
        envelope: EventEnvelopeV1,
        authorization: AuthorizationContext,
    ) -> AdmissionResult:
        fingerprint = event_fingerprint(envelope)
        try:
            return await self._insert_admission(envelope, authorization, fingerprint)
        except IntegrityError as error:
            try:
                return await self._load_duplicate(envelope, authorization, fingerprint)
            except RuntimeError:
                raise error from None

    async def _insert_admission(
        self,
        envelope: EventEnvelopeV1,
        authorization: AuthorizationContext,
        fingerprint: bytes,
    ) -> AdmissionResult:
        async with self._sessions() as session, session.begin():
            existing = await self._find_event(session, envelope, authorization.scope_id)
            if existing is not None:
                return await self._duplicate_result(session, existing, fingerprint)

            run_id = str(uuid4())
            job_id = str(uuid4())
            session.add(
                EventRecord(
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
            )
            session.add(
                RunRecord(
                    id=run_id,
                    scope_id=authorization.scope_id,
                    event_id=envelope.id,
                    workflow="alert",
                    workflow_contract_version="1",
                    thread_id=run_id,
                    status=RunStatus.QUEUED.value,
                )
            )
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
                return await self._claim_jobs(worker_id, limit=limit)
        return await self._claim_jobs(worker_id, limit=limit)

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
