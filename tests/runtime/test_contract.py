from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from platform_agent_orchestrator.runtime import RunStatus
from platform_agent_orchestrator.runtime.langgraph import (
    LangGraphCheckpoint,
    LangGraphWorkflowRuntime,
)
from platform_agent_orchestrator.sdk import (
    FLOW_END,
    BaseFlow,
    ConditionalRoute,
    EdgeSpec,
    FlowDefinition,
    FlowMetadata,
    NodeContext,
    NodeOutcome,
    NodeSpec,
    PauseRequest,
)

from .helpers import context, event


class RuntimeState(TypedDict, total=False):
    event: dict[str, Any]
    run_id: str
    first: bool
    second: str
    route: str
    selected: str
    left: bool
    right: bool
    prepared: bool
    approved: bool


class ContractFlow(BaseFlow):
    def __init__(self, name: str, definition: FlowDefinition) -> None:
        self.metadata = FlowMetadata(
            name=name,
            version="1.0.0",
            event_types=frozenset({"runtime.test.received"}),
        )
        self._definition = definition

    def define(self) -> FlowDefinition:
        return self._definition


def test_linear_flow_runs_to_framework_terminal() -> None:
    def first(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
        return {"first": node.node_name == "first"}

    async def second(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
        return {"second": "complete" if state["first"] else "invalid"}

    flow = ContractFlow(
        "linear",
        FlowDefinition(
            state_schema=RuntimeState,
            entrypoint="first",
            nodes=[NodeSpec("first", first), NodeSpec("second", second)],
            edges=[EdgeSpec("first", "second"), EdgeSpec("second", FLOW_END)],
        ),
    )

    result = asyncio.run(
        LangGraphWorkflowRuntime().start(flow, event(), context=context("linear-run"))
    )

    assert result.status == RunStatus.SUCCEEDED
    assert result.output["first"] is True
    assert result.output["second"] == "complete"


def test_conditional_route_selects_one_branch() -> None:
    def classify(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
        return {"route": state["event"]["data"]["route"]}

    def left(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
        return {"selected": "left"}

    def right(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
        return {"selected": "right"}

    flow = ContractFlow(
        "conditional",
        FlowDefinition(
            state_schema=RuntimeState,
            entrypoint="classify",
            nodes=[
                NodeSpec("classify", classify),
                NodeSpec("left", left),
                NodeSpec("right", right),
            ],
            edges=[EdgeSpec("left", FLOW_END), EdgeSpec("right", FLOW_END)],
            conditional_routes=[
                ConditionalRoute(
                    source="classify",
                    router=lambda state: state["route"],
                    routes={"left": "left", "right": "right"},
                )
            ],
        ),
    )

    result = asyncio.run(
        LangGraphWorkflowRuntime().start(flow, event(), context=context("conditional-run"))
    )

    assert result.status == RunStatus.SUCCEEDED
    assert result.output["selected"] == "right"


def test_parallel_edges_execute_both_branches_concurrently() -> None:
    started: set[str] = set()
    both_started = asyncio.Event()

    def fan_out(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
        return {}

    async def branch(name: str) -> dict[str, bool]:
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return {name: True}

    async def left(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
        return await branch("left")

    async def right(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
        return await branch("right")

    flow = ContractFlow(
        "parallel",
        FlowDefinition(
            state_schema=RuntimeState,
            entrypoint="fan_out",
            nodes=[
                NodeSpec("fan_out", fan_out),
                NodeSpec("left", left),
                NodeSpec("right", right),
            ],
            edges=[
                EdgeSpec("fan_out", "left"),
                EdgeSpec("fan_out", "right"),
                EdgeSpec("left", FLOW_END),
                EdgeSpec("right", FLOW_END),
            ],
        ),
    )

    result = asyncio.run(
        LangGraphWorkflowRuntime().start(flow, event(), context=context("parallel-run"))
    )

    assert result.status == RunStatus.SUCCEEDED
    assert result.output["left"] is True
    assert result.output["right"] is True


def test_pause_and_resume_translate_framework_outcome() -> None:
    def approval(state: dict[str, Any], node: NodeContext) -> NodeOutcome | dict[str, Any]:
        if node.resume_payload is None:
            return NodeOutcome(
                updates={"prepared": True},
                pause=PauseRequest(
                    reason="Approve deterministic runtime test",
                    approval_id="approval-1",
                    payload={"resource": "test"},
                ),
            )
        return {"approved": node.resume_payload.get("approved") is True}

    flow = ContractFlow(
        "pause-resume",
        FlowDefinition(
            state_schema=RuntimeState,
            entrypoint="approval",
            nodes=[NodeSpec("approval", approval)],
            edges=[EdgeSpec("approval", FLOW_END)],
        ),
    )
    runtime = LangGraphWorkflowRuntime()
    execution_context = context("pause-run")

    paused = asyncio.run(runtime.start(flow, event(), context=execution_context))

    assert paused.status == RunStatus.PAUSED
    assert paused.pause is not None
    assert paused.pause.approval_id == "approval-1"
    assert paused.output["prepared"] is True

    resumed = asyncio.run(
        runtime.resume("pause-run", {"approved": True}, context=execution_context)
    )

    assert resumed.status == RunStatus.SUCCEEDED
    assert resumed.output["prepared"] is True
    assert resumed.output["approved"] is True


def test_fresh_runtime_resumes_from_checkpoint_with_registry_resolved_flow() -> None:
    def approval(state: dict[str, Any], node: NodeContext) -> NodeOutcome | dict[str, Any]:
        if node.resume_payload is None:
            return NodeOutcome(
                pause=PauseRequest(
                    reason="Durable restart review",
                    approval_id="approval-restart",
                )
            )
        return {"approved": node.resume_payload.get("approved") is True}

    flow = ContractFlow(
        "restart-resume",
        FlowDefinition(
            state_schema=RuntimeState,
            entrypoint="approval",
            nodes=[NodeSpec("approval", approval)],
            edges=[EdgeSpec("approval", FLOW_END)],
        ),
    )
    checkpoint = LangGraphCheckpoint()
    execution_context = context("restart-run")
    first_runtime = LangGraphWorkflowRuntime(checkpointer=checkpoint.saver)

    paused = asyncio.run(first_runtime.start(flow, event(), context=execution_context))
    assert paused.status is RunStatus.PAUSED

    fresh_runtime = LangGraphWorkflowRuntime(checkpointer=checkpoint.saver)
    resumed = asyncio.run(
        fresh_runtime.resume(
            "restart-run",
            {"approved": True},
            context=execution_context,
            flow=flow,
        )
    )

    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.output["approved"] is True
