"""Runtime-neutral Engineering assistance flow."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, cast

from platform_agent_orchestrator.core.capabilities import (
    CapabilityRequest,
    CapabilityResult,
)
from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.memory import MemoryItem
from platform_agent_orchestrator.core.models import EvidenceRef
from platform_agent_orchestrator.sdk.agent import Agent, AgentRequest
from platform_agent_orchestrator.sdk.flow import (
    FLOW_END,
    BaseFlow,
    EdgeSpec,
    FlowDefinition,
    FlowMetadata,
    NodeSpec,
)
from platform_agent_orchestrator.sdk.nodes import NodeContext

ROLE_AGENTS = {
    "developer": "engineering.developer",
    "qa": "engineering.qa",
    "ba": "engineering.ba",
}


class EngineeringState(TypedDict, total=False):
    event: dict[str, Any]
    run_id: str
    question: str
    requested_role: str
    role: str
    evidence: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    memory_available: bool
    decision: dict[str, Any]
    evidence_verified: bool
    answer: str
    status: str


class CapabilityAccess(Protocol):
    def has(self, capability: str) -> bool: ...

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult: ...


class AgentAccess(Protocol):
    def get(self, name: str) -> Agent: ...


class EngineeringFlow(BaseFlow):
    metadata = FlowMetadata(
        name="engineering-assistance",
        version="2.0.0",
        event_types=frozenset({"engineering.question.received"}),
        required_capabilities=frozenset({"knowledge.search"}),
        optional_capabilities=frozenset({"memory.recall"}),
        tags=frozenset({"builtin", "engineering"}),
    )

    def define(self) -> FlowDefinition:
        return FlowDefinition(
            state_schema=EngineeringState,
            entrypoint="normalize",
            nodes=[
                NodeSpec("normalize", _normalize),
                NodeSpec("route", _route),
                NodeSpec("retrieve_knowledge", _retrieve_knowledge),
                NodeSpec("recall_memory", _recall_memory),
                NodeSpec("invoke_agent", _invoke_agent),
                NodeSpec("verify_evidence", _verify_evidence),
            ],
            edges=[
                EdgeSpec("normalize", "route"),
                EdgeSpec("route", "retrieve_knowledge"),
                EdgeSpec("retrieve_knowledge", "recall_memory"),
                EdgeSpec("recall_memory", "invoke_agent"),
                EdgeSpec("invoke_agent", "verify_evidence"),
                EdgeSpec("verify_evidence", FLOW_END),
            ],
        )


def _normalize(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    event = state.get("event")
    if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
        raise ValueError("engineering flow requires a runtime-neutral event object")
    data = event["data"]
    question = str(data.get("question", "")).strip()
    if not question:
        raise ValueError("engineering question must be non-empty")
    return {
        "question": question,
        "requested_role": str(data.get("role", "auto")).strip().lower(),
    }


def _route(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    requested = state["requested_role"]
    question = state["question"].lower()
    aliases = {
        "developer": "developer",
        "qa": "qa",
        "ba": "ba",
        "product": "ba",
        "business-analyst": "ba",
    }
    if requested in aliases:
        role = aliases[requested]
    elif any(token in question for token in ("test", "regression", "coverage")):
        role = "qa"
    elif any(token in question for token in ("user", "business", "owner", "feature")):
        role = "ba"
    else:
        role = "developer"
    return {"role": role}


async def _retrieve_knowledge(
    state: dict[str, Any],
    node: NodeContext,
) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="knowledge.search",
            operation="search",
            arguments={"query": state["question"], "limit": 8},
        ),
        context=node.execution,
    )
    if not result.success:
        raise RuntimeError(result.error or "knowledge.search failed")
    evidence = _model_items(result.data, "evidence", EvidenceRef)
    return {"evidence": [item.model_dump(mode="json") for item in evidence]}


async def _recall_memory(
    state: dict[str, Any],
    node: NodeContext,
) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    if not capabilities.has("memory.recall"):
        return {"memories": [], "memory_available": False}
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="memory.recall",
            operation="recall",
            arguments={
                "query": state["question"],
                "scope": f"engineering/{state['role']}",
                "limit": 5,
            },
        ),
        context=node.execution,
    )
    if not result.success:
        return {"memories": [], "memory_available": False}
    memories = _model_items(result.data, "memories", MemoryItem)
    return {
        "memories": [item.model_dump(mode="json") for item in memories],
        "memory_available": True,
    }


async def _invoke_agent(
    state: dict[str, Any],
    node: NodeContext,
) -> dict[str, Any]:
    agents = cast(AgentAccess, node.execution.agents)
    role = state["role"]
    agent = agents.get(ROLE_AGENTS[role])
    result = await agent.invoke(
        request=_agent_request(state),
        context=node.execution,
    )
    return {"decision": result.output}


def _agent_request(state: dict[str, Any]) -> AgentRequest:
    return AgentRequest(
        task=state["question"],
        input={"role": state["role"]},
        evidence=[EvidenceRef.model_validate(item) for item in state.get("evidence", [])],
        memories=[MemoryItem.model_validate(item) for item in state.get("memories", [])],
    )


def _verify_evidence(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    available = {
        EvidenceRef.model_validate(item).locator for item in state.get("evidence", [])
    }
    decision = state["decision"]
    cited = {str(item) for item in decision.get("evidence_ids", [])}
    verified = bool(cited) and cited.issubset(available)
    answer = str(decision.get("summary", ""))
    if verified:
        answer += f" Evidence: {', '.join(sorted(cited))}."
    else:
        answer += " Evidence could not be fully verified; treat this as provisional."
    return {
        "evidence_verified": verified,
        "answer": answer,
        "status": "answered" if verified else "provisional",
    }


def _model_items(data: Any, key: str, model: type[Any]) -> list[Any]:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise TypeError(f"capability result must contain a {key!r} list")
    return [model.model_validate(item) for item in data[key]]
