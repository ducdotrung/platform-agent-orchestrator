"""Runtime-neutral workflow execution interface."""

from __future__ import annotations

from typing import Any, Protocol

from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.events import DomainEvent
from platform_agent_orchestrator.sdk.flow import Flow

from .execution import RunResult


class WorkflowRuntime(Protocol):
    """Start and resume flows without exposing implementation-library types."""

    async def start(
        self,
        flow: Flow,
        event: DomainEvent,
        *,
        context: ExecutionContext,
    ) -> RunResult:
        """Start one flow for an admitted event."""

        ...

    async def resume(
        self,
        run_id: str,
        payload: dict[str, Any],
        *,
        context: ExecutionContext,
        flow: Flow | None = None,
    ) -> RunResult:
        """Resume using a flow reconstructed from durable metadata when supplied."""

        ...
