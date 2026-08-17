from __future__ import annotations

import asyncio
from typing import Any

import pytest

from platform_agent_orchestrator.core import DomainEvent, ExecutionContext
from platform_agent_orchestrator.registry import FlowRegistry
from platform_agent_orchestrator.runtime import RunMetadata, RunResult, RunStatus
from platform_agent_orchestrator.runtime.context import ExecutionContextFactory
from platform_agent_orchestrator.runtime.dispatcher import Dispatcher, FlowVersionMismatch
from platform_agent_orchestrator.sdk import BaseFlow, FlowDefinition, FlowMetadata

from .helpers import event


class DispatchFlow(BaseFlow):
    def __init__(self, name: str, event_type: str = "runtime.test.received") -> None:
        self.metadata = FlowMetadata(
            name=name,
            version="1.0.0",
            event_types=frozenset({event_type}),
        )

    def define(self) -> FlowDefinition:
        return FlowDefinition(state_schema=dict, entrypoint="unused")


class RecordingRuntime:
    def __init__(self) -> None:
        self.starts: list[tuple[str, ExecutionContext]] = []
        self.resumes: list[tuple[str, str, ExecutionContext]] = []

    async def start(
        self,
        flow: DispatchFlow,
        event: DomainEvent,
        *,
        context: ExecutionContext,
    ) -> RunResult:
        del event
        self.starts.append((flow.metadata.name, context))
        return RunResult(
            run_id=context.identity.run_id,
            flow=flow.metadata.name,
            status=RunStatus.SUCCEEDED,
        )

    async def resume(
        self,
        run_id: str,
        payload: dict[str, Any],
        *,
        context: ExecutionContext,
        flow: DispatchFlow | None = None,
    ) -> RunResult:
        del payload
        assert flow is not None
        self.resumes.append((run_id, flow.metadata.name, context))
        return RunResult(
            run_id=run_id,
            flow=flow.metadata.name,
            status=RunStatus.SUCCEEDED,
        )


def dispatcher_for(*flows: DispatchFlow) -> tuple[Dispatcher, RecordingRuntime]:
    registry = FlowRegistry()
    for flow in flows:
        registry.register(flow)
    runtime = RecordingRuntime()
    dispatcher = Dispatcher(
        flows=registry,
        runtime=runtime,
        contexts=ExecutionContextFactory(
            capabilities=object(),
            agents=object(),
            policy=object(),
            observability=object(),
        ),
    )
    return dispatcher, runtime


def test_dispatches_one_matching_flow() -> None:
    dispatcher, runtime = dispatcher_for(DispatchFlow("one"))

    results = asyncio.run(dispatcher.dispatch(event()))

    assert [result.flow for result in results] == ["one"]
    assert [name for name, _context in runtime.starts] == ["one"]


def test_dispatches_multiple_matching_flows_with_distinct_runs() -> None:
    dispatcher, runtime = dispatcher_for(DispatchFlow("one"), DispatchFlow("two"))

    results = asyncio.run(dispatcher.dispatch(event()))

    assert [result.flow for result in results] == ["one", "two"]
    assert len({result.run_id for result in results}) == 2
    assert len(runtime.starts) == 2


def test_dispatch_with_no_matching_flow_returns_empty() -> None:
    dispatcher, runtime = dispatcher_for(DispatchFlow("other", "other.event"))

    assert asyncio.run(dispatcher.dispatch(event())) == []
    assert runtime.starts == []


def test_durable_resume_resolves_exact_registered_flow_version() -> None:
    dispatcher, runtime = dispatcher_for(DispatchFlow("durable"))
    run = RunMetadata(
        run_id="run-1",
        flow_name="durable",
        flow_version="1.0.0",
        thread_id="thread-1",
        correlation_id="correlation-1",
        tenant_id="tenant-1",
        status="paused",
    )

    result = asyncio.run(dispatcher.resume(run, {"approved": True}))

    assert result.status is RunStatus.SUCCEEDED
    assert runtime.resumes[0][2].identity.tenant_id == "tenant-1"

    with pytest.raises(FlowVersionMismatch):
        asyncio.run(
            dispatcher.resume(
                run.model_copy(update={"flow_version": "2.0.0"}),
                {"approved": True},
            )
        )
