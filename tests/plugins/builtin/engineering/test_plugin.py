from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from platform_agent_orchestrator.core import (
    CapabilityRequest,
    CapabilityResult,
    DomainEvent,
    EvidenceRef,
    ExecutionContext,
)
from platform_agent_orchestrator.plugins.builtin.engineering import (
    EngineeringFlow,
)
from platform_agent_orchestrator.plugins.builtin.engineering import (
    plugin as engineering_plugin,
)
from platform_agent_orchestrator.registry import (
    AgentRegistry,
    CapabilityRegistry,
    FlowRegistry,
    validate_registry,
)
from platform_agent_orchestrator.runtime import RunResult, RunStatus
from platform_agent_orchestrator.runtime.context import ExecutionContextFactory
from platform_agent_orchestrator.runtime.dispatcher import Dispatcher
from platform_agent_orchestrator.runtime.langgraph import LangGraphWorkflowRuntime
from platform_agent_orchestrator.sdk import (
    AgentRequest,
    AgentResult,
    PluginContext,
)

PLUGIN_ROOT = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "platform_agent_orchestrator"
    / "plugins"
    / "builtin"
    / "engineering"
)


@dataclass
class RecordingCapabilities:
    include_memory: bool = True
    requests: list[CapabilityRequest] = field(default_factory=list)

    @property
    def capabilities(self) -> frozenset[str]:
        names = {"knowledge.search"}
        if self.include_memory:
            names.add("memory.recall")
        return frozenset(names)

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        del context
        self.requests.append(request)
        if request.capability == "knowledge.search":
            evidence = EvidenceRef(
                kind="graph",
                locator="service://checkout/payment",
                revision="demo-rev-1",
                label="Checkout calls payment during order completion",
            )
            return CapabilityResult(
                success=True,
                data={"evidence": [evidence.model_dump(mode="json")]},
            )
        if request.capability == "memory.recall" and self.include_memory:
            return CapabilityResult(
                success=True,
                data={
                    "memories": [
                        {
                            "id": "memory-1",
                            "content": "Timeout changes previously needed retry tests",
                            "score": 0.9,
                            "metadata": {},
                        }
                    ]
                },
            )
        return CapabilityResult(success=False, error="unsupported")


@dataclass
class RecordingAgent:
    name: str = "engineering.developer"
    requests: list[AgentRequest] = field(default_factory=list)

    async def invoke(
        self,
        request: AgentRequest,
        *,
        context: ExecutionContext,
    ) -> AgentResult:
        del context
        self.requests.append(request)
        return AgentResult(
            output={
                "summary": "Recorded developer response",
                "role": "developer",
                "agent_name": self.name,
                "evidence_ids": [item.locator for item in request.evidence],
                "memory_ids": [item.id for item in request.memories],
            }
        )


class Policies:
    def register(self, name: str, policy: object) -> None:
        del name, policy


def question_event(question: str, role: str = "auto") -> DomainEvent:
    return DomainEvent(
        id="engineering-event-1",
        type="engineering.question.received",
        source="engineering-tests",
        subject="question-1",
        occurred_at=datetime(2026, 8, 17, tzinfo=UTC),
        correlation_id="engineering-correlation-1",
        idempotency_key=f"engineering:{role}:{question}",
        tenant_id="tenant-1",
        data={"question": question, "role": role},
    )


def plugin_context(
    *,
    capabilities: CapabilityRegistry,
    agents: AgentRegistry | None = None,
    flows: FlowRegistry | None = None,
) -> tuple[PluginContext, AgentRegistry, FlowRegistry]:
    agent_registry = agents or AgentRegistry()
    flow_registry = flows or FlowRegistry()
    return (
        PluginContext(
            flows=flow_registry,
            agents=agent_registry,
            capabilities=capabilities,
            policies=Policies(),
        ),
        agent_registry,
        flow_registry,
    )


def run_flow(
    question: str,
    *,
    role: str = "auto",
    include_memory: bool = True,
    agents: AgentRegistry | None = None,
) -> tuple[RunResult, RecordingCapabilities]:
    provider = RecordingCapabilities(include_memory=include_memory)
    capabilities = CapabilityRegistry()
    capabilities.register(provider)
    context, agent_registry, flows = plugin_context(
        capabilities=capabilities,
        agents=agents,
    )
    if agents is None:
        engineering_plugin.register(context)
    else:
        flows.register(EngineeringFlow())
    validate_registry(flows=flows, capabilities=capabilities)
    dispatcher = Dispatcher(
        flows=flows,
        runtime=LangGraphWorkflowRuntime(),
        contexts=ExecutionContextFactory(
            capabilities=capabilities,
            agents=agent_registry,
            policy=object(),
            observability=object(),
        ),
    )
    results = asyncio.run(dispatcher.dispatch(question_event(question, role)))
    assert len(results) == 1
    return results[0], provider


@pytest.mark.parametrize(
    ("question", "requested_role", "expected_role", "expected_agent"),
    [
        ("How should I change the client?", "developer", "developer", "engineering.developer"),
        ("What regression coverage is needed?", "auto", "qa", "engineering.qa"),
        ("What user impact does this feature have?", "auto", "ba", "engineering.ba"),
    ],
)
def test_role_routing(
    question: str,
    requested_role: str,
    expected_role: str,
    expected_agent: str,
) -> None:
    result, _provider = run_flow(question, role=requested_role)

    assert result.status is RunStatus.SUCCEEDED
    assert result.output["role"] == expected_role
    assert result.output["decision"]["agent_name"] == expected_agent


def test_registered_agent_is_invoked_with_knowledge_and_memory() -> None:
    agent = RecordingAgent()
    agents = AgentRegistry()
    agents.register(agent)

    result, provider = run_flow(
        "How should I change the client?",
        role="developer",
        agents=agents,
    )

    assert result.status is RunStatus.SUCCEEDED
    assert len(agent.requests) == 1
    assert agent.requests[0].evidence[0].locator == "service://checkout/payment"
    assert agent.requests[0].memories[0].id == "memory-1"
    memory_request = provider.requests[1]
    assert memory_request.arguments == {
        "query": "How should I change the client?",
        "scope": "engineering/developer",
        "limit": 5,
    }
    assert [request.capability for request in provider.requests] == [
        "knowledge.search",
        "memory.recall",
    ]


def test_knowledge_retrieval_is_cited_and_verified() -> None:
    result, provider = run_flow("What regression coverage is needed?")

    assert provider.requests[0].operation == "search"
    assert provider.requests[0].arguments["query"] == "What regression coverage is needed?"
    assert result.output["evidence_verified"] is True
    assert "service://checkout/payment" in result.output["answer"]


def test_missing_optional_memory_falls_back_without_failure() -> None:
    result, provider = run_flow(
        "What regression coverage is needed?",
        include_memory=False,
    )

    assert result.status is RunStatus.SUCCEEDED
    assert result.output["memory_available"] is False
    assert result.output["decision"]["memory_ids"] == []
    assert [request.capability for request in provider.requests] == ["knowledge.search"]


def test_missing_agent_returns_failed_runtime_result() -> None:
    result, _provider = run_flow(
        "What regression coverage is needed?",
        agents=AgentRegistry(),
    )

    assert result.status is RunStatus.FAILED
    assert result.error is not None and "UnknownAgentError" in result.error


def test_builtin_plugin_registration_and_dependency_boundary() -> None:
    capabilities = CapabilityRegistry()
    capabilities.register(RecordingCapabilities())
    context, agents, flows = plugin_context(capabilities=capabilities)

    engineering_plugin.register(context)
    validate_registry(flows=flows, capabilities=capabilities)

    assert set(agents.list()) == {
        "engineering.developer",
        "engineering.qa",
        "engineering.ba",
    }
    flow = flows.get("engineering-assistance")
    assert flow.metadata.required_capabilities == frozenset({"knowledge.search"})
    assert flow.metadata.optional_capabilities == frozenset({"memory.recall"})

    forbidden: list[str] = []
    for path in PLUGIN_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if module.startswith(
                    ("lang" + "chain", "langgraph", "platform_agent_orchestrator.adapters")
                ):
                    forbidden.append(f"{path.name}:{node.lineno}:{module}")
    assert forbidden == []
