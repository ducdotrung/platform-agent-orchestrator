"""Safety-gated SRE ticket execution workflow."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from platform_agent_orchestrator.adapters.ports import PlatformServices
from platform_agent_orchestrator.contracts import ActionRequest, ActionResult, Approval, RiskLevel

from .common import dump_evidence, load_event, load_evidence


class SREState(TypedDict, total=False):
    event: dict[str, Any]
    ticket: dict[str, Any]
    evidence: list[dict[str, Any]]
    plan: list[dict[str, Any]]
    risk: str
    approval: dict[str, Any]
    action_results: list[dict[str, Any]]
    verified: bool
    notification_receipt: str
    status: str


def build_sre_execution_graph(
    services: PlatformServices, *, checkpointer: Any | None = None
) -> Any:
    def normalize(state: SREState) -> dict[str, Any]:
        event = load_event(state)
        payload = event.payload
        ticket = {
            "key": str(payload.get("key", event.subject)),
            "summary": str(payload.get("summary", "SRE request")),
            "service": str(payload.get("service", "unknown-service")),
            "environment": str(payload.get("environment", "dev")),
            "operation": str(payload.get("operation", "inspect")),
        }
        return {"ticket": ticket}

    def retrieve(state: SREState) -> dict[str, Any]:
        ticket = state["ticket"]
        query = (
            f"{ticket['service']} {ticket['environment']} {ticket['operation']} "
            "runbook rollback dependencies"
        )
        return {"evidence": dump_evidence(services.knowledge.search(query))}

    def plan(state: SREState) -> dict[str, Any]:
        requests = services.reasoner.plan_sre(
            state["ticket"], load_evidence(state.get("evidence", []))
        )
        return {"plan": [request.model_dump(mode="json") for request in requests]}

    def classify_risk(state: SREState) -> dict[str, Any]:
        requests = [ActionRequest.model_validate(item) for item in state["plan"]]
        levels = {request.risk for request in requests}
        if RiskLevel.RISKY in levels:
            risk = RiskLevel.RISKY
        elif RiskLevel.CAUTION in levels:
            risk = RiskLevel.CAUTION
        else:
            risk = RiskLevel.SAFE
        return {"risk": risk.value}

    def after_risk(state: SREState) -> str:
        return "approval" if state["risk"] != RiskLevel.SAFE else "execute"

    def approval(state: SREState) -> dict[str, Any]:
        response = interrupt(
            {
                "kind": "sre_action_approval",
                "ticket": state["ticket"],
                "risk": state["risk"],
                "actions": state["plan"],
                "message": "Approve these bounded SRE actions?",
            }
        )
        if isinstance(response, bool):
            response = {"approved": response, "actor": "unknown", "reason": "No reason supplied"}
        return {"approval": Approval.model_validate(response).model_dump(mode="json")}

    def after_approval(state: SREState) -> str:
        return "execute" if state["approval"]["approved"] else "rejected"

    def execute(state: SREState) -> dict[str, Any]:
        results = [
            services.actions.execute(ActionRequest.model_validate(item)) for item in state["plan"]
        ]
        return {"action_results": [result.model_dump(mode="json") for result in results]}

    def verify(state: SREState) -> dict[str, Any]:
        results = [ActionResult.model_validate(item) for item in state["action_results"]]
        return {"verified": all(services.actions.verify(result) for result in results)}

    def after_verification(state: SREState) -> str:
        return "notify" if state["verified"] else "failed"

    def notify(state: SREState) -> dict[str, Any]:
        event = load_event(state)
        receipt = services.notifier.send(
            "sre-operations",
            f"Completed and verified {state['ticket']['key']}: {state['ticket']['summary']}",
            idempotency_key=f"{event.idempotency_key}:completion",
        )
        return {"notification_receipt": receipt, "status": "completed"}

    def rejected(state: SREState) -> dict[str, Any]:
        return {"status": "rejected"}

    def failed(state: SREState) -> dict[str, Any]:
        return {"status": "verification_failed"}

    builder = StateGraph(SREState)
    builder.add_node("normalize", normalize)
    builder.add_node("retrieve", retrieve)
    builder.add_node("plan", plan)
    builder.add_node("classify_risk", classify_risk)
    builder.add_node("approval", approval)
    builder.add_node("execute", execute)
    builder.add_node("verify", verify)
    builder.add_node("notify", notify)
    builder.add_node("rejected", rejected)
    builder.add_node("failed", failed)
    builder.add_edge(START, "normalize")
    builder.add_edge("normalize", "retrieve")
    builder.add_edge("retrieve", "plan")
    builder.add_edge("plan", "classify_risk")
    builder.add_conditional_edges(
        "classify_risk", after_risk, {"approval": "approval", "execute": "execute"}
    )
    builder.add_conditional_edges(
        "approval", after_approval, {"execute": "execute", "rejected": "rejected"}
    )
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges(
        "verify", after_verification, {"notify": "notify", "failed": "failed"}
    )
    builder.add_edge("notify", END)
    builder.add_edge("rejected", END)
    builder.add_edge("failed", END)
    return builder.compile(checkpointer=checkpointer)
