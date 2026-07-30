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
            return

        summary = _bounded_summary(result)
        try:
            if "__interrupt__" in result:
                await self.outcomes.record_interruption(claim, summary)
            else:
                await self.outcomes.record_success(claim, summary)
        except LeaseLost:
            pass

    async def shutdown(self) -> None:
        self._stopping.set()
        await self.dispatcher.shutdown()


def _error_fingerprint(category: RetryCategory, error: BaseException) -> bytes:
    identity = f"{category.value}:{type(error).__module__}.{type(error).__qualname__}"
    return hashlib.sha256(identity.encode()).digest()


def _bounded_summary(result: dict[str, Any]) -> str:
    summary = {
        "status": result.get("status", "interrupted" if "__interrupt__" in result else "completed"),
        "interrupted": "__interrupt__" in result,
    }
    return json.dumps(summary, separators=(",", ":"), sort_keys=True)
