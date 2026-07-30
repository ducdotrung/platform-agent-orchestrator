from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from platform_agent_orchestrator.dispatcher import DatabaseJobDispatcher
from platform_agent_orchestrator.persistence import ClaimedJob
from platform_agent_orchestrator.service_contracts import RetryCategory
from platform_agent_orchestrator.worker import (
    RetryableWorkerError,
    TerminalWorkerError,
    Worker,
)

NOW = datetime(2026, 7, 30, tzinfo=UTC)


def claimed_job() -> ClaimedJob:
    return ClaimedJob(
        job_id="job-1",
        run_id="run-1",
        kind="invoke",
        lease_token="lease-1",
        attempt_number=1,
        lease_expires_at=NOW + timedelta(seconds=30),
    )


class OneJobSource:
    def __init__(self) -> None:
        self.sent = False

    async def claim_jobs(self, worker_id: str, *, limit: int = 1) -> list[ClaimedJob]:
        if self.sent:
            return []
        self.sent = True
        return [claimed_job()]


class FakeExecutor:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome

    async def execute(self, claim: ClaimedJob) -> dict[str, Any]:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome  # type: ignore[return-value]


class RecordingOutcomes:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def record_success(self, claim: ClaimedJob, summary: str) -> None:
        self.calls.append(("success", {"summary": summary}))

    async def record_interruption(self, claim: ClaimedJob, summary: str) -> None:
        self.calls.append(("interruption", {"summary": summary}))

    async def record_retry(self, claim: ClaimedJob, **values: Any) -> None:
        self.calls.append(("retry", values))

    async def record_terminal_failure(self, claim: ClaimedJob, **values: Any) -> None:
        self.calls.append(("terminal", values))


def run_worker(outcome: object) -> RecordingOutcomes:
    async def scenario() -> RecordingOutcomes:
        outcomes = RecordingOutcomes()
        worker = Worker(
            worker_id="worker-1",
            dispatcher=DatabaseJobDispatcher(OneJobSource()),
            executor=FakeExecutor(outcome),
            outcomes=outcomes,
            clock=lambda: NOW,
        )
        assert await worker.run_once() == 1
        return outcomes

    return asyncio.run(scenario())


def test_worker_records_success_and_interruption() -> None:
    success = run_worker({"status": "notified"})
    interrupted = run_worker({"__interrupt__": [{"kind": "review"}]})

    assert success.calls[0][0] == "success"
    assert '"status":"notified"' in success.calls[0][1]["summary"]
    assert interrupted.calls[0][0] == "interruption"
    summary = json.loads(interrupted.calls[0][1]["summary"])
    assert summary["approval"]["kind"] == "review"
    assert len(summary["approval"]["action_hash"]) == 64


def test_worker_classifies_retryable_and_terminal_failures() -> None:
    retry = run_worker(RetryableWorkerError())
    terminal = run_worker(TerminalWorkerError(RetryCategory.TERMINAL_INPUT))

    assert retry.calls[0][0] == "retry"
    assert retry.calls[0][1]["category"] == "retryable_transient"
    assert retry.calls[0][1]["available_at"] == NOW + timedelta(seconds=1)
    assert len(retry.calls[0][1]["fingerprint"]) == 32
    assert terminal.calls[0][0] == "terminal"
    assert terminal.calls[0][1]["category"] == "terminal_input"


def test_worker_error_categories_cannot_cross_retry_policy() -> None:
    with pytest.raises(ValueError):
        RetryableWorkerError(RetryCategory.TERMINAL_INPUT)
    with pytest.raises(ValueError):
        TerminalWorkerError(RetryCategory.WORKER_LOST)


def test_unexpected_exception_is_terminal_and_message_is_not_persisted() -> None:
    outcomes = run_worker(RuntimeError("password=do-not-persist"))

    assert outcomes.calls[0][0] == "terminal"
    assert outcomes.calls[0][1]["category"] == "terminal_dependency"
    assert "do-not-persist" not in str(outcomes.calls)


def test_worker_shutdown_stops_future_claims() -> None:
    async def scenario() -> None:
        source = OneJobSource()
        worker = Worker(
            worker_id="worker-1",
            dispatcher=DatabaseJobDispatcher(source),
            executor=FakeExecutor({"status": "done"}),
            outcomes=RecordingOutcomes(),
        )
        await worker.shutdown()

        assert await worker.run_once() == 0
        assert source.sent is False

    asyncio.run(scenario())
