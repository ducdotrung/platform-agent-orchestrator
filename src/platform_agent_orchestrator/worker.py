"""Async worker lifecycle around fenced delivery jobs and the workflow registry."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from platform_agent_orchestrator.dispatcher import DatabaseJobDispatcher, DispatcherClosed
from platform_agent_orchestrator.persistence import ClaimedJob, EventRepository, LeaseLost
from platform_agent_orchestrator.runtime import RunResult, RunStatus
from platform_agent_orchestrator.runtime.dispatcher import Dispatcher
from platform_agent_orchestrator.service_contracts import RetryCategory
from platform_agent_orchestrator.telemetry import PublicEventLogger, ServiceMetrics


class WorkflowExecution(Protocol):
    async def execute(self, claim: ClaimedJob) -> RunResult: ...


class OutcomeStore(Protocol):
    async def record_success(self, claim: ClaimedJob, summary: str) -> None: ...

    async def record_interruption(self, claim: ClaimedJob, summary: str) -> None: ...

    async def record_retry(
        self,
        claim: ClaimedJob,
        *,
        category: str,
        fingerprint: bytes,
        available_at: datetime,
    ) -> None: ...

    async def record_terminal_failure(
        self,
        claim: ClaimedJob,
        *,
        category: str,
        fingerprint: bytes,
    ) -> None: ...


class RetryableWorkerError(RuntimeError):
    def __init__(self, category: RetryCategory = RetryCategory.RETRYABLE_TRANSIENT) -> None:
        if category not in {RetryCategory.RETRYABLE_TRANSIENT, RetryCategory.WORKER_LOST}:
            raise ValueError("retryable worker errors require a retryable category")
        super().__init__(category.value)
        self.category = category


class TerminalWorkerError(RuntimeError):
    def __init__(self, category: RetryCategory = RetryCategory.TERMINAL_DEPENDENCY) -> None:
        if category in {RetryCategory.RETRYABLE_TRANSIENT, RetryCategory.WORKER_LOST}:
            raise ValueError("terminal worker errors require a terminal category")
        super().__init__(category.value)
        self.category = category


@dataclass(frozen=True)
class RegistryExecution:
    repository: EventRepository
    dispatcher: Dispatcher

    async def execute(self, claim: ClaimedJob) -> RunResult:
        run = await self.repository.load_claimed_run(claim)
        if claim.kind == "resume":
            decision = await self.repository.load_claimed_resume(claim)
            return await self.dispatcher.resume(run, decision)
        event = await self.repository.load_claimed_event(claim)
        return await self.dispatcher.execute(run, event)


@dataclass
class Worker:
    worker_id: str
    dispatcher: DatabaseJobDispatcher
    executor: WorkflowExecution
    outcomes: OutcomeStore
    retry_delay: timedelta = timedelta(seconds=1)
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    metrics: ServiceMetrics | None = None
    event_logger: PublicEventLogger | None = None
    _stopping: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    async def run_once(self) -> int:
        if self._stopping.is_set():
            return 0
        try:
            claims = await self.dispatcher.claim(self.worker_id, limit=1)
        except DispatcherClosed:
            return 0
        completed = 0
        for claim in claims:
            if self._stopping.is_set():
                break
            await self._execute_claim(claim)
            completed += 1
        return completed

    async def _execute_claim(self, claim: ClaimedJob) -> None:
        try:
            result = await self.executor.execute(claim)
        except LeaseLost:
            self._observe("lease_lost")
            return
        except RetryableWorkerError as error:
            try:
                await self.outcomes.record_retry(
                    claim,
                    category=error.category.value,
                    fingerprint=_error_fingerprint(error.category, error),
                    available_at=self.clock() + self.retry_delay,
                )
            except LeaseLost:
                pass
            self._observe("retry")
            return
        except TerminalWorkerError as error:
            try:
                await self.outcomes.record_terminal_failure(
                    claim,
                    category=error.category.value,
                    fingerprint=_error_fingerprint(error.category, error),
                )
            except LeaseLost:
                pass
            self._observe("terminal_failure")
            return
        except Exception as error:
            category = RetryCategory.TERMINAL_DEPENDENCY
            try:
                await self.outcomes.record_terminal_failure(
                    claim,
                    category=category.value,
                    fingerprint=_error_fingerprint(category, error),
                )
            except LeaseLost:
                pass
            self._observe("terminal_failure")
            return

        if result.status not in {RunStatus.PAUSED, RunStatus.SUCCEEDED}:
            category = RetryCategory.TERMINAL_DEPENDENCY
            try:
                await self.outcomes.record_terminal_failure(
                    claim,
                    category=category.value,
                    fingerprint=_run_failure_fingerprint(result),
                )
            except LeaseLost:
                pass
            self._observe("terminal_failure", workflow=result.flow)
            return

        summary = _bounded_summary(result, now=self.clock())
        try:
            if result.status is RunStatus.PAUSED:
                await self.outcomes.record_interruption(claim, summary)
                self._observe("interrupted", workflow=result.flow)
            elif result.status is RunStatus.SUCCEEDED:
                await self.outcomes.record_success(claim, summary)
                self._observe("succeeded", workflow=result.flow)
        except LeaseLost:
            self._observe("lease_lost")

    async def shutdown(self) -> None:
        self._stopping.set()
        await self.dispatcher.shutdown()

    def _observe(self, outcome: str, *, workflow: str = "unknown") -> None:
        try:
            if self.metrics is not None:
                self.metrics.worker_outcomes.labels(outcome).inc()
            if self.event_logger is not None:
                self.event_logger.info(
                    "worker_outcome",
                    outcome=outcome,
                    workflow=workflow,
                )
        except Exception:
            pass


def _error_fingerprint(category: RetryCategory, error: BaseException) -> bytes:
    identity = f"{category.value}:{type(error).__module__}.{type(error).__qualname__}"
    return hashlib.sha256(identity.encode()).digest()


def _run_failure_fingerprint(result: RunResult) -> bytes:
    identity = f"runtime_failed:{result.flow}:{result.status.value}"
    return hashlib.sha256(identity.encode()).digest()


def _bounded_summary(result: RunResult, *, now: datetime | None = None) -> str:
    summary = {
        "status": result.output.get("status", result.status.value),
        "interrupted": result.status is RunStatus.PAUSED,
    }
    if result.pause is not None:
        interrupt_value = result.pause.payload
        canonical = json.dumps(
            interrupt_value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        decided_by = now or datetime.now(UTC)
        action_hash = (
            result.pause.approval.action_hash
            if result.pause.approval is not None
            else hashlib.sha256(canonical).hexdigest()
        )
        summary["approval"] = {
            "approval_version": 1,
            "kind": str(interrupt_value.get("kind", "workflow_review"))[:64],
            "action_hash": action_hash,
            "expires_at": (decided_by + timedelta(minutes=15)).isoformat(),
        }
    return json.dumps(summary, separators=(",", ":"), sort_keys=True)
