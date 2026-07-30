"""Durable, fenced execution for logical notification side effects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from platform_agent_orchestrator.adapters.ports import NotificationPort
from platform_agent_orchestrator.persistence import AuditEventRecord, SideEffectRecord


class SideEffectConflict(ValueError):
    pass


class SideEffectInProgress(RuntimeError):
    pass


class AmbiguousSideEffect(RuntimeError):
    pass


@dataclass(frozen=True)
class SideEffectClaim:
    effect_id: str
    claim_token: str | None
    receipt: str | None = None

    @property
    def requires_execution(self) -> bool:
        return self.claim_token is not None


class SideEffectStore(Protocol):
    def reserve_notification(
        self,
        *,
        scope_id: str,
        run_id: str,
        channel: str,
        message: str,
        idempotency_key: str,
        provider: str,
    ) -> SideEffectClaim: ...

    def complete_notification(self, claim: SideEffectClaim, receipt: str) -> None: ...

    def mark_unknown(self, claim: SideEffectClaim) -> None: ...


class DatabaseSideEffectStore:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        claim_duration: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._claim_duration = claim_duration
        self._clock = clock

    def reserve_notification(
        self,
        *,
        scope_id: str,
        run_id: str,
        channel: str,
        message: str,
        idempotency_key: str,
        provider: str,
    ) -> SideEffectClaim:
        request_hash = notification_request_hash(channel, message)
        ambiguous = False
        with self._sessions.begin() as session:
            effect = session.scalar(
                sa.select(SideEffectRecord)
                .where(
                    SideEffectRecord.scope_id == scope_id,
                    SideEffectRecord.effect_kind == "notification",
                    SideEffectRecord.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            now = self._clock()
            if effect is None:
                effect = SideEffectRecord(
                    id=str(uuid4()),
                    scope_id=scope_id,
                    run_id=run_id,
                    effect_kind="notification",
                    destination=channel,
                    provider=provider,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    status="reserved",
                    reserved_at=now,
                )
                try:
                    with session.begin_nested():
                        session.add(effect)
                        session.flush()
                except IntegrityError:
                    effect = session.scalar(
                        sa.select(SideEffectRecord)
                        .where(
                            SideEffectRecord.scope_id == scope_id,
                            SideEffectRecord.effect_kind == "notification",
                            SideEffectRecord.idempotency_key == idempotency_key,
                        )
                        .with_for_update()
                    )
                    if effect is None:
                        raise RuntimeError("side-effect conflict has no durable record") from None
            if effect.request_hash != request_hash:
                raise SideEffectConflict("side-effect key was reused with changed content")
            if (
                effect.run_id != run_id
                or effect.destination != channel
                or effect.provider != provider
            ):
                raise SideEffectConflict("side-effect key was reused in a different context")

            if effect.status == "succeeded":
                receipt = effect.receipt or {}
                return SideEffectClaim(effect.id, None, str(receipt.get("receipt", "")))
            if effect.status == "unknown":
                raise AmbiguousSideEffect("notification outcome requires reconciliation")
            if effect.status == "in_progress":
                expires_at = _as_utc(effect.claim_expires_at)
                if expires_at is not None and expires_at > now:
                    raise SideEffectInProgress("notification is already in progress")
                prior_state = effect.status
                effect.status = "unknown"
                effect.claim_token = None
                effect.claim_expires_at = None
                effect.version += 1
                self._audit(
                    session,
                    effect,
                    outcome="ambiguous",
                    reason="expired_claim",
                    prior_state=prior_state,
                    new_state="unknown",
                )
                ambiguous = True
            elif effect.status != "reserved":
                raise SideEffectConflict(f"side effect cannot execute from {effect.status}")
            if not ambiguous:
                token = str(uuid4())
                prior_state = effect.status
                effect.status = "in_progress"
                effect.claim_token = token
                effect.claim_expires_at = now + self._claim_duration
                effect.started_at = effect.started_at or now
                effect.attempt_count += 1
                effect.version += 1
                self._audit(
                    session,
                    effect,
                    outcome="claimed",
                    reason="ready",
                    prior_state=prior_state,
                    new_state="in_progress",
                )
                claim = SideEffectClaim(effect.id, token)
        if ambiguous:
            raise AmbiguousSideEffect("expired notification claim requires reconciliation")
        return claim

    def complete_notification(self, claim: SideEffectClaim, receipt: str) -> None:
        if not claim.claim_token:
            raise ValueError("completion requires an active claim")
        if not receipt or len(receipt) > 256:
            raise ValueError("receipt must contain 1 to 256 characters")
        with self._sessions.begin() as session:
            effect = self._load_claim(session, claim)
            effect.status = "succeeded"
            effect.receipt = {"receipt": receipt}
            effect.provider_reference = receipt
            effect.claim_token = None
            effect.claim_expires_at = None
            effect.completed_at = self._clock()
            effect.version += 1
            self._audit(
                session,
                effect,
                outcome="succeeded",
                reason="provider_receipt",
                prior_state="in_progress",
                new_state="succeeded",
            )

    def mark_unknown(self, claim: SideEffectClaim) -> None:
        if not claim.claim_token:
            raise ValueError("unknown outcome requires an active claim")
        with self._sessions.begin() as session:
            effect = self._load_claim(session, claim)
            effect.status = "unknown"
            effect.claim_token = None
            effect.claim_expires_at = None
            effect.version += 1
            self._audit(
                session,
                effect,
                outcome="ambiguous",
                reason="provider_outcome_unknown",
                prior_state="in_progress",
                new_state="unknown",
            )

    @staticmethod
    def _load_claim(session: Session, claim: SideEffectClaim) -> SideEffectRecord:
        effect = session.scalar(
            sa.select(SideEffectRecord)
            .where(
                SideEffectRecord.id == claim.effect_id,
                SideEffectRecord.status == "in_progress",
                SideEffectRecord.claim_token == claim.claim_token,
            )
            .with_for_update()
        )
        if effect is None:
            raise SideEffectConflict("side-effect claim fence was lost")
        return effect

    @staticmethod
    def _audit(
        session: Session,
        effect: SideEffectRecord,
        *,
        outcome: str,
        reason: str,
        prior_state: str,
        new_state: str,
    ) -> None:
        session.add(
            AuditEventRecord(
                scope_id=effect.scope_id,
                actor_type="service",
                actor_id="side-effect-executor",
                action="side_effect.notification",
                outcome=outcome,
                reason_code=reason,
                run_id=effect.run_id,
                side_effect_id=effect.id,
                prior_state=prior_state,
                new_state=new_state,
                action_hash=effect.request_hash,
                metadata_json={"provider": effect.provider},
            )
        )


@dataclass(frozen=True)
class DurableNotifier:
    store: SideEffectStore
    provider: NotificationPort
    scope_id: str
    provider_name: str = "demo-notifier"

    def send(
        self,
        channel: str,
        message: str,
        *,
        idempotency_key: str,
        run_id: str | None = None,
    ) -> str:
        if run_id is None:
            raise ValueError("durable notification requires run_id")
        claim = self.store.reserve_notification(
            scope_id=self.scope_id,
            run_id=run_id,
            channel=channel,
            message=message,
            idempotency_key=idempotency_key,
            provider=self.provider_name,
        )
        if not claim.requires_execution:
            if not claim.receipt:
                raise SideEffectConflict("successful side effect has no receipt")
            return claim.receipt
        try:
            receipt = self.provider.send(
                channel,
                message,
                idempotency_key=idempotency_key,
                run_id=run_id,
            )
        except Exception:
            self.store.mark_unknown(claim)
            raise
        self.store.complete_notification(claim, receipt)
        return receipt


def notification_request_hash(channel: str, message: str) -> bytes:
    if not channel or len(channel) > 256:
        raise ValueError("notification channel must contain 1 to 256 characters")
    if not message or len(message) > 16_384:
        raise ValueError("notification message must contain 1 to 16384 characters")
    canonical = json.dumps(
        {"channel": channel, "message": message},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).digest()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
