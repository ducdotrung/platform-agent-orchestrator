from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from platform_agent_orchestrator.core import (
    CapabilityRequest,
    CapabilityResult,
    DomainEvent,
    ExecutionContext,
    ExecutionIdentity,
)
from platform_agent_orchestrator.sdk import (
    AgentRequest,
    AgentResult,
    BaseFlow,
    FlowDefinition,
    FlowMetadata,
)


class DummyFlow(BaseFlow):
    def __init__(
        self,
        name: str,
        *,
        event_types: frozenset[str] = frozenset({"test.event.received"}),
        required_capabilities: frozenset[str] = frozenset(),
        optional_capabilities: frozenset[str] = frozenset(),
    ) -> None:
        self.metadata = FlowMetadata(
            name=name,
            version="1.0.0",
            event_types=event_types,
            required_capabilities=required_capabilities,
            optional_capabilities=optional_capabilities,
        )

    def define(self) -> FlowDefinition:
        return FlowDefinition(state_schema=dict, entrypoint="start")


@dataclass
class DummyAgent:
    name: str

    async def invoke(
        self,
        request: AgentRequest,
        *,
        context: ExecutionContext,
    ) -> AgentResult:
        return AgentResult(output={"task": request.task})


class DummyProvider:
    def __init__(self, *capabilities: str) -> None:
        self._capabilities = frozenset(capabilities)
        self.requests: list[CapabilityRequest] = []

    @property
    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        self.requests.append(request)
        return CapabilityResult(success=True, data={"capability": request.capability})


def domain_event(event_type: str = "test.event.received") -> DomainEvent:
    return DomainEvent(
        id="event-1",
        type=event_type,
        source="registry-tests",
        occurred_at=datetime(2026, 8, 16, tzinfo=UTC),
        correlation_id="correlation-1",
        idempotency_key=f"test:{event_type}",
    )


def execution_context() -> ExecutionContext:
    return ExecutionContext(
        identity=ExecutionIdentity(
            run_id="run-1",
            thread_id="thread-1",
            correlation_id="correlation-1",
        ),
        capabilities=object(),
        agents=object(),
        policy=object(),
        observability=object(),
        metadata={},
    )
