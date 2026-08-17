"""WorkflowRuntime adapter for flows awaiting their builtin-plugin migrations."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from platform_agent_orchestrator.contracts import DomainEvent as LegacyDomainEvent
from platform_agent_orchestrator.contracts import EventType
from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.events import DomainEvent
from platform_agent_orchestrator.registry.legacy import WorkflowRegistry
from platform_agent_orchestrator.runtime.engine import WorkflowRuntime
from platform_agent_orchestrator.runtime.execution import RunResult, RunStatus
from platform_agent_orchestrator.sdk.flow import BaseFlow, Flow, FlowDefinition, FlowMetadata
from platform_agent_orchestrator.sdk.nodes import PauseRequest


class LegacyFlowHandle(BaseFlow):
    """Registry identity for a legacy flow; it contains no compiled graph."""

    def __init__(self, name: str, version: str, event_type: str) -> None:
        self.metadata = FlowMetadata(
            name=name,
            version=version,
            event_types=frozenset({event_type}),
        )

    def define(self) -> FlowDefinition:
        raise RuntimeError("legacy flow definitions are owned by LegacyWorkflowRuntime")


class LegacyWorkflowRuntime:
    """Keep pre-migration flows behind the generic runtime boundary."""

    def __init__(self, registry: WorkflowRegistry) -> None:
        self._registry = registry

    async def start(
        self,
        flow: Flow,
        event: DomainEvent,
        *,
        context: ExecutionContext,
    ) -> RunResult:
        try:
            result = await asyncio.to_thread(
                self._registry.invoke,
                flow.metadata.name,
                _legacy_event(event),
                thread_id=context.identity.thread_id,
            )
        except Exception as error:
            return _failed(flow, context.identity.run_id, error)
        return _translate_result(flow, context.identity.run_id, result)

    async def resume(
        self,
        run_id: str,
        payload: dict[str, Any],
        *,
        context: ExecutionContext,
        flow: Flow | None = None,
    ) -> RunResult:
        if flow is None:
            return RunResult(
                run_id=run_id,
                flow="unknown",
                status=RunStatus.FAILED,
                error="durable resume requires a registry-resolved flow",
            )
        try:
            result = await asyncio.to_thread(
                self._registry.resume,
                flow.metadata.name,
                thread_id=context.identity.thread_id,
                decision=payload,
            )
        except Exception as error:
            return _failed(flow, run_id, error)
        return _translate_result(flow, run_id, result)


class TransitionalWorkflowRuntime:
    """Route migrated flows to the v2 runtime and deferred flows to legacy."""

    def __init__(
        self,
        *,
        primary: WorkflowRuntime,
        legacy: LegacyWorkflowRuntime,
    ) -> None:
        self._primary = primary
        self._legacy = legacy

    async def start(
        self,
        flow: Flow,
        event: DomainEvent,
        *,
        context: ExecutionContext,
    ) -> RunResult:
        runtime = self._legacy if isinstance(flow, LegacyFlowHandle) else self._primary
        return await runtime.start(flow, event, context=context)

    async def resume(
        self,
        run_id: str,
        payload: dict[str, Any],
        *,
        context: ExecutionContext,
        flow: Flow | None = None,
    ) -> RunResult:
        runtime = self._legacy if isinstance(flow, LegacyFlowHandle) else self._primary
        return await runtime.resume(
            run_id,
            payload,
            context=context,
            flow=flow,
        )


def _legacy_event(event: DomainEvent) -> LegacyDomainEvent:
    return LegacyDomainEvent(
        id=event.id,
        type=EventType(event.type),
        source=event.source,
        subject=event.subject or event.id,
        occurred_at=event.occurred_at,
        correlation_id=event.correlation_id,
        idempotency_key=event.idempotency_key,
        payload=event.data,
    )


def _translate_result(flow: Flow, run_id: str, result: dict[str, Any]) -> RunResult:
    raw_interrupts = result.get("__interrupt__")
    pause = None
    if raw_interrupts:
        values = (
            list(raw_interrupts)
            if isinstance(raw_interrupts, (list, tuple))
            else [raw_interrupts]
        )
        if len(values) != 1:
            raise ValueError("exactly one legacy workflow interrupt is supported")
        value = getattr(values[0], "value", values[0])
        if not isinstance(value, dict):
            raise ValueError("legacy workflow interrupt must contain an object")
        digest = hashlib.sha256(repr(sorted(value.items())).encode()).hexdigest()[:24]
        pause = PauseRequest(
            reason=str(value.get("message") or value.get("kind") or "Workflow paused"),
            approval_id=f"legacy-{digest}",
            payload=value,
        )
    output = {key: value for key, value in result.items() if key != "__interrupt__"}
    return RunResult(
        run_id=run_id,
        flow=flow.metadata.name,
        status=RunStatus.PAUSED if pause is not None else RunStatus.SUCCEEDED,
        output=output,
        pause=pause,
    )


def _failed(flow: Flow, run_id: str, error: Exception) -> RunResult:
    return RunResult(
        run_id=run_id,
        flow=flow.metadata.name,
        status=RunStatus.FAILED,
        error=f"{type(error).__name__}: {error}",
    )
