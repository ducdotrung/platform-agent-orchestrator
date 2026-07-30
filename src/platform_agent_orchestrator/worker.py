"""Async worker lifecycle around fenced delivery jobs and the workflow registry."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from platform_agent_orchestrator.dispatcher import DatabaseJobDispatcher, DispatcherClosed
from platform_agent_orchestrator.persistence import ClaimedJob, EventRepository, LeaseLost
from platform_agent_orchestrator.registry import WorkflowRegistry
from platform_agent_orchestrator.service_contracts import RetryCategory
from platform_agent_orchestrator.telemetry import PublicEventLogger, ServiceMetrics


class WorkflowExecution(Protocol):
    async def execute(self, claim: ClaimedJob) -> dict[str, Any]: ...


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
    registry: WorkflowRegistry

    async def execute(self, claim: ClaimedJob) -> dict[str, Any]:
        if claim.kind == "resume":
            decision = await self.repository.load_claimed_resume(claim)
            return await asyncio.to_thread(
                self.registry.resume,
                "alert",
                thread_id=claim.run_id,
                decision=decision,
            )
        event = await self.repository.load_claimed_event(claim)
        return await asyncio.to_thread(
            self.registry.invoke,
            "alert",
            event,
            thread_id=claim.run_id,
        )


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

        summary = _bounded_summary(result, now=self.clock())
        try:
            if "__interrupt__" in result:
                await self.outcomes.record_interruption(claim, summary)
                self._observe("interrupted")
            else:
                await self.outcomes.record_success(claim, summary)
                self._observe("succeeded")
        except LeaseLost:
            self._observe("lease_lost")

    async def shutdown(self) -> None:
        self._stopping.set()
        await self.dispatcher.shutdown()

    def _observe(self, outcome: str) -> None:
        try:
            if self.metrics is not None:
                self.metrics.worker_outcomes.labels(outcome).inc()
            if self.event_logger is not None:
                self.event_logger.info("worker_outcome", outcome=outcome, workflow="alert")
        except Exception:
            pass


def _error_fingerprint(category: RetryCategory, error: BaseException) -> bytes:
    identity = f"{category.value}:{type(error).__module__}.{type(error).__qualname__}"
    return hashlib.sha256(identity.encode()).digest()


def _bounded_summary(result: dict[str, Any], *, now: datetime | None = None) -> str:
    summary = {
        "status": result.get("status", "interrupted" if "__interrupt__" in result else "completed"),
        "interrupted": "__interrupt__" in result,
    }
    if "__interrupt__" in result:
        interrupt_value = _interrupt_value(result["__interrupt__"])
        canonical = json.dumps(
            interrupt_value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        decided_by = now or datetime.now(UTC)
        summary["approval"] = {
            "approval_version": 1,
            "kind": str(interrupt_value.get("kind", "workflow_review"))[:64],
            "action_hash": hashlib.sha256(canonical).hexdigest(),
            "expires_at": (decided_by + timedelta(minutes=15)).isoformat(),
        }
    return json.dumps(summary, separators=(",", ":"), sort_keys=True)


def _interrupt_value(raw: Any) -> dict[str, Any]:
    values = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    if len(values) != 1:
        raise ValueError("exactly one workflow interrupt is supported")
    value = getattr(values[0], "value", values[0])
    if not isinstance(value, dict):
        raise ValueError("workflow interrupt must contain an object")
    return value
