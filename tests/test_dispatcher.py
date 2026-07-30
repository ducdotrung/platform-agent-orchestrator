from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from platform_agent_orchestrator.dispatcher import (
    DatabaseJobDispatcher,
    DispatcherClosed,
    PoisonDeliveryRecord,
)
from platform_agent_orchestrator.persistence import ClaimedJob

NOW = datetime(2026, 7, 30, tzinfo=UTC)


def claim() -> ClaimedJob:
    return ClaimedJob(
        job_id="job-1",
        run_id="run-1",
        kind="invoke",
        lease_token="lease-1",
        attempt_number=1,
        lease_expires_at=NOW + timedelta(seconds=30),
    )


class RecordingSource:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def claim_jobs(self, worker_id: str, *, limit: int = 1) -> list[ClaimedJob]:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome  # type: ignore[return-value]


def test_transient_claim_failure_retries_without_publication() -> None:
    async def scenario() -> None:
        source = RecordingSource([TimeoutError(), [claim()]])
        dispatcher = DatabaseJobDispatcher(source, retry_base_seconds=0)

        claimed = await dispatcher.claim("worker-1")

        assert claimed == [claim()]
        assert source.calls == 2

    asyncio.run(scenario())


def test_active_duplicate_claim_returns_no_second_delivery() -> None:
    async def scenario() -> None:
        source = RecordingSource([[claim()], []])
        dispatcher = DatabaseJobDispatcher(source)

        assert len(await dispatcher.claim("worker-1")) == 1
        assert await dispatcher.claim("worker-2") == []

    asyncio.run(scenario())


def test_poison_claim_is_rejected_without_retry() -> None:
    async def scenario() -> None:
        source = RecordingSource([[replace(claim(), kind="unknown")]])
        dispatcher = DatabaseJobDispatcher(source)

        with pytest.raises(PoisonDeliveryRecord):
            await dispatcher.claim("worker-1")
        assert source.calls == 1

    asyncio.run(scenario())


def test_shutdown_stops_new_and_retrying_claims() -> None:
    async def scenario() -> None:
        retry_started = asyncio.Event()

        async def sleeper(_delay: float) -> None:
            retry_started.set()
            await asyncio.Event().wait()

        source = RecordingSource([ConnectionError(), [claim()]])
        dispatcher = DatabaseJobDispatcher(source, sleeper=sleeper)
        pending = asyncio.create_task(dispatcher.claim("worker-1"))
        await retry_started.wait()
        await dispatcher.shutdown()

        with pytest.raises(DispatcherClosed):
            await pending
        with pytest.raises(DispatcherClosed):
            await dispatcher.claim("worker-2")
        assert source.calls == 1

    asyncio.run(scenario())
