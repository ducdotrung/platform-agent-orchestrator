from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from platform_agent_orchestrator.contracts import AlertReceivedPayloadV1, EventEnvelopeV1
from platform_agent_orchestrator.persistence import (
    DeliveryAttemptRecord,
    DeliveryJobRecord,
    EventRecord,
    EventRepository,
    IdempotencyConflict,
    LeaseLost,
    RunRecord,
)
from platform_agent_orchestrator.security import AuthorizationContext
from platform_agent_orchestrator.service_contracts import DeliveryStatus, RunStatus

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def migration_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def envelope(*, key: str = "sample:orders:1", title: str = "Orders errors") -> EventEnvelopeV1:
    return EventEnvelopeV1(
        source="sample-sre-alert-agent",
        subject="orders-high-errors",
        idempotency_key=key,
        payload=AlertReceivedPayloadV1(
            alert_id="orders-high-errors",
            title=title,
            service="orders",
            severity="critical",
            environment="sample",
            count=42,
            users=7,
        ),
    )


def authorization() -> AuthorizationContext:
    return AuthorizationContext(
        actor_id="sample-sre-alert-agent",
        scope_id="sock-shop-sample",
    )


async def repository_for(
    tmp_path: Path,
    *,
    clock: list[datetime] | None = None,
) -> tuple[EventRepository, AsyncEngine, async_sessionmaker]:
    database = tmp_path / f"repository-{uuid4()}.db"
    sync_url = f"sqlite:///{database}"
    command.upgrade(migration_config(sync_url), "head")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database}",
        execution_options={"schema_translate_map": {"orchestrator": None}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = EventRepository(
        sessions,
        clock=(lambda: clock[0]) if clock is not None else (lambda: NOW),
    )
    return repository, engine, sessions


def test_duplicate_event_returns_stable_run_and_changed_content_conflicts(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repository, engine, sessions = await repository_for(tmp_path)
        try:
            first_event = envelope()
            first = await repository.admit_event(first_event, authorization())
            transport_retry = first_event.model_copy(
                update={
                    "id": str(uuid4()),
                    "correlation_id": str(uuid4()),
                    "occurred_at": NOW + timedelta(minutes=1),
                }
            )
            duplicate = await repository.admit_event(transport_retry, authorization())

            assert duplicate.run_id == first.run_id
            assert duplicate.duplicate is True
            with pytest.raises(IdempotencyConflict):
                await repository.admit_event(
                    envelope(title="Changed business content"), authorization()
                )

            async with sessions() as session:
                event_count = await session.scalar(
                    sa.select(sa.func.count()).select_from(EventRecord)
                )
                assert event_count == 1
                assert await session.scalar(sa.select(sa.func.count()).select_from(RunRecord)) == 1
                assert (
                    await session.scalar(sa.select(sa.func.count()).select_from(DeliveryJobRecord))
                    == 1
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_admission_transaction_rolls_back_all_business_rows(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository, engine, sessions = await repository_for(tmp_path)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(
                        "CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events "
                        "BEGIN SELECT RAISE(ABORT, 'injected audit failure'); END"
                    )
                )

            with pytest.raises(IntegrityError):
                await repository.admit_event(envelope(), authorization())

            async with sessions() as session:
                for model in (EventRecord, RunRecord, DeliveryJobRecord):
                    count = await session.scalar(sa.select(sa.func.count()).select_from(model))
                    assert count == 0
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_concurrent_claim_returns_job_to_one_worker_only(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository, engine, _sessions = await repository_for(tmp_path)
        try:
            await repository.admit_event(envelope(), authorization())
            first, second = await asyncio.gather(
                repository.claim_jobs("worker-a"),
                repository.claim_jobs("worker-b"),
            )

            assert sorted((len(first), len(second))) == [0, 1]
            claim = (first or second)[0]
            assert claim.attempt_number == 1
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_expired_lease_is_reclaimed_and_prior_attempt_is_closed(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = [NOW]
        repository, engine, sessions = await repository_for(tmp_path, clock=clock)
        try:
            await repository.admit_event(envelope(), authorization())
            first = (await repository.claim_jobs("worker-a"))[0]
            clock[0] = NOW + timedelta(seconds=31)
            second = (await repository.claim_jobs("worker-b"))[0]

            assert second.job_id == first.job_id
            assert second.lease_token != first.lease_token
            assert second.attempt_number == 2
            async with sessions() as session:
                attempts = list(
                    (
                        await session.scalars(
                            sa.select(DeliveryAttemptRecord).order_by(
                                DeliveryAttemptRecord.attempt_number
                            )
                        )
                    ).all()
                )
                assert attempts[0].outcome == "worker_lost"
                assert attempts[0].finished_at is not None
                assert attempts[1].finished_at is None
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_success_transition_is_atomic_and_fenced(tmp_path: Path) -> None:
    async def scenario() -> None:
        repository, engine, sessions = await repository_for(tmp_path)
        try:
            admission = await repository.admit_event(envelope(), authorization())
            claim = (await repository.claim_jobs("worker-a"))[0]
            loaded = await repository.load_claimed_event(claim)

            assert loaded.idempotency_key == "sample:orders:1"
            await repository.record_success(claim, '{"status":"completed"}')

            async with sessions() as session:
                job = await session.get(DeliveryJobRecord, claim.job_id)
                run = await session.get(RunRecord, admission.run_id)
                attempt = await session.scalar(
                    sa.select(DeliveryAttemptRecord).where(
                        DeliveryAttemptRecord.job_id == claim.job_id
                    )
                )
                assert job is not None and job.status == DeliveryStatus.COMPLETED.value
                assert job.lease_token is None and job.completed_at is not None
                assert run is not None and run.status == RunStatus.SUCCEEDED.value
                assert run.finished_at is not None
                assert attempt is not None and attempt.outcome == "succeeded"

            with pytest.raises(LeaseLost):
                await repository.record_success(claim, "duplicate")
        finally:
            await engine.dispose()

    asyncio.run(scenario())
