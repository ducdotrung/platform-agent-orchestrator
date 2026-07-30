"""Brokerless dispatcher over authoritative PostgreSQL delivery jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from platform_agent_orchestrator.persistence import ClaimedJob


class DeliverySource(Protocol):
    async def claim_jobs(self, worker_id: str, *, limit: int = 1) -> list[ClaimedJob]: ...


class DispatcherClosed(RuntimeError):
    pass


class PoisonDeliveryRecord(ValueError):
    pass


@dataclass
class DatabaseJobDispatcher:
    """Retry bounded claim calls; job rows replace a separate publish broker."""

    source: DeliverySource
    max_claim_retries: int = 3
    retry_base_seconds: float = 0.05
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep
    _closed: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    async def claim(self, worker_id: str, *, limit: int = 1) -> list[ClaimedJob]:
        if self._closed.is_set():
            raise DispatcherClosed("dispatcher is closed")
        for attempt in range(1, self.max_claim_retries + 1):
            try:
                claimed = await self.source.claim_jobs(worker_id, limit=limit)
            except (ConnectionError, TimeoutError, OSError):
                if attempt == self.max_claim_retries:
                    raise
                await self._wait_or_close(self.retry_base_seconds * 2 ** (attempt - 1))
                continue
            for job in claimed:
                self._validate(job)
            return claimed
        raise AssertionError("bounded retry loop did not terminate")

    async def _wait_or_close(self, delay: float) -> None:
        if delay <= 0:
            await self.sleeper(0)
            if self._closed.is_set():
                raise DispatcherClosed("dispatcher closed during retry")
            return
        sleep_task = asyncio.create_task(self.sleeper(delay))
        close_task = asyncio.create_task(self._closed.wait())
        done, pending = await asyncio.wait(
            {sleep_task, close_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if close_task in done and close_task.result():
            raise DispatcherClosed("dispatcher closed during retry")

    async def shutdown(self) -> None:
        self._closed.set()

    @staticmethod
    def _validate(job: ClaimedJob) -> None:
        if (
            not job.job_id
            or not job.run_id
            or job.kind not in {"invoke", "resume"}
            or not job.lease_token
            or job.attempt_number < 1
            or job.lease_expires_at.tzinfo is None
        ):
            raise PoisonDeliveryRecord("claimed delivery record violates the contract")
