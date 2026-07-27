"""Role-routed engineering knowledge assistant workflow."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from platform_agent_orchestrator.adapters.ports import PlatformServices

from .common import dump_evidence, load_event, load_evidence


class EngineeringState(TypedDict, total=False):
    event: dict[str, Any]
    question: str
    requested_role: str
    role: str
    evidence: list[dict[str, Any]]
    decision: dict[str, Any]
    evidence_verified: bool
    answer: str
    status: str


def build_engineering_graph(services: PlatformServices, *, checkpointer: Any | None = None) -> Any:
    def normalize(state: EngineeringState) -> dict[str, Any]:
        event = load_event(state)
        return {
            "question": str(event.payload.get("question", "")),
            "requested_role": str(event.payload.get("role", "auto")).lower(),
        }

    def route(state: EngineeringState) -> dict[str, Any]:
        requested = state["requested_role"]
        question = state["question"].lower()
        if requested in {"developer", "qa", "product"}:
            role = requested
        elif any(token in question for token in ("test", "regression", "coverage")):
            role = "qa"
        elif any(token in question for token in ("user", "business", "owner", "feature")):
            role = "product"
        else:
            role = "developer"
        return {"role": role}

    def retrieve(state: EngineeringState) -> dict[str, Any]:
        evidence = services.knowledge.search(state["question"])
        return {"evidence": dump_evidence(evidence)}

    def role_agent(role: str):
        def run(state: EngineeringState) -> dict[str, Any]:
            decision = services.reasoner.answer_engineering(
                role, state["question"], load_evidence(state.get("evidence", []))
            )
            return {"decision": decision.model_dump(mode="json")}

        return run

    def choose_role(state: EngineeringState) -> str:
        return state["role"]

    def verify_evidence(state: EngineeringState) -> dict[str, Any]:
        available = {item["id"] for item in state.get("evidence", [])}
        cited = set(state["decision"].get("evidence_ids", []))
        verified = bool(cited) and cited.issubset(available)
        answer = state["decision"]["summary"]
        if verified:
            answer += f" Evidence: {', '.join(sorted(cited))}."
        else:
            answer += " Evidence could not be fully verified; treat this as provisional."
        return {
            "evidence_verified": verified,
            "answer": answer,
            "status": "answered" if verified else "provisional",
        }

    builder = StateGraph(EngineeringState)
    builder.add_node("normalize", normalize)
    builder.add_node("route", route)
    builder.add_node("retrieve", retrieve)
    builder.add_node("developer", role_agent("developer"))
    builder.add_node("qa", role_agent("qa"))
    builder.add_node("product", role_agent("product"))
    builder.add_node("verify_evidence", verify_evidence)
    builder.add_edge(START, "normalize")
    builder.add_edge("normalize", "route")
    builder.add_edge("route", "retrieve")
    builder.add_conditional_edges(
        "retrieve",
        choose_role,
        {"developer": "developer", "qa": "qa", "product": "product"},
    )
    for role in ("developer", "qa", "product"):
        builder.add_edge(role, "verify_evidence")
    builder.add_edge("verify_evidence", END)
    return builder.compile(checkpointer=checkpointer)
