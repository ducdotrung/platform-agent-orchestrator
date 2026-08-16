from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from platform_agent_orchestrator.core import DomainEvent
from platform_agent_orchestrator.sdk import (
    BaseFlow,
    ConditionalRoute,
    EdgeSpec,
    FlowDefinition,
    FlowMetadata,
    NodeContext,
    NodeSpec,
)


class ExampleState(TypedDict, total=False):
    answer: str


def answer_node(state: dict[str, object], context: NodeContext) -> dict[str, object]:
    return {"answer": f"{context.node_name}:{state.get('question', '')}"}


class DummyFlow(BaseFlow):
    metadata = FlowMetadata(
        name="external-example",
        version="1.0.0",
        event_types=frozenset({"customer.extension.happened"}),
        required_capabilities=frozenset({"knowledge.search"}),
    )

    def define(self) -> FlowDefinition:
        return FlowDefinition(
            state_schema=ExampleState,
            entrypoint="answer",
            nodes=[NodeSpec(name="answer", handler=answer_node)],
            edges=[EdgeSpec(source="answer", target="done")],
            conditional_routes=[
                ConditionalRoute(
                    source="answer",
                    router=lambda state: "complete" if state.get("answer") else "retry",
                    routes={"complete": "done", "retry": "answer"},
                )
            ],
        )


def event(event_type: str) -> DomainEvent:
    return DomainEvent(
        id="event-1",
        type=event_type,
        source="test",
        occurred_at=datetime(2026, 8, 16, tzinfo=UTC),
        correlation_id="correlation-1",
        idempotency_key="test:event-1",
    )


def test_dummy_flow_is_defined_without_runtime_library_types() -> None:
    definition = DummyFlow().define()

    assert definition.state_schema is ExampleState
    assert definition.entrypoint == "answer"
    assert [node.name for node in definition.nodes] == ["answer"]
    assert definition.conditional_routes[0].routes["complete"] == "done"


def test_base_flow_accepts_only_declared_namespaced_events() -> None:
    flow = DummyFlow()

    assert flow.accepts(event("customer.extension.happened"))
    assert not flow.accepts(event("monitoring.alert.received"))
