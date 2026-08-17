"""Typed provider-neutral memory integration port."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.memory import MemoryItem, MemoryQuery, MemoryRecord


class MemoryPortError(RuntimeError):
    """Expected provider failure safe to expose as a failed capability result."""


@runtime_checkable
class MemoryPort(Protocol):
    """Recall and selectively update execution learnings."""

    async def recall(
        self,
        query: MemoryQuery,
        *,
        context: ExecutionContext,
    ) -> list[MemoryItem]: ...

    async def record(
        self,
        record: MemoryRecord,
        *,
        context: ExecutionContext,
    ) -> str: ...

    async def feedback(
        self,
        memory_id: str,
        *,
        useful: bool,
        reason: str | None,
        context: ExecutionContext,
    ) -> None: ...
