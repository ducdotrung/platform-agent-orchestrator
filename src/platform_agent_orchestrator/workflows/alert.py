"""Evidence-enriched alert triage and recommendation workflow."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from platform_agent_orchestrator.adapters.ports import PlatformServices
from platform_agent_orchestrator.contracts import Approval, DecisionStatus

from .common import dump_evidence, load_event, load_evidence


class AlertState(TypedDict, total=False):
    event: dict[str, Any]
    run_id: str
    alert: dict[str, Any]
    suppressed: bool
    suppression_reason: str
    evidence: list[dict[str, Any]]
    decision: dict[str, Any]
    require_human_review: bool
    approval: dict[str, Any]
    recommendation: str
    notification_receipt: str
    status: str


def build_alert_graph(services: PlatformServices, *, checkpointer: Any | None = None) -> Any:
    def normalize(state: AlertState) -> dict[str, Any]:
        event = load_event(state)
        payload = event.payload
        alert = {
            "id": str(payload.get("alert_id", event.subject)),
            "title": str(payload.get("title", "Untitled alert")),
            "service": str(payload.get("service", "unknown-service")),
            "severity": str(payload.get("severity", "warning")).lower(),
            "count": int(payload.get("count", 1)),
            "users": int(payload.get("users", 0)),
            "environment": str(payload.get("environment", "unknown")),
        }
        return {"alert": alert}

    def classify(state: AlertState) -> dict[str, Any]:
        alert = dict(state["alert"])
        title = alert["title"].lower()
        known_noise = ("client disconnected", "cancelled request", "health check")
        suppressed = any(marker in title for marker in known_noise) and alert["count"] < 100
        if suppressed:
            return {
                "suppressed": True,
                "suppression_reason": "Matched a bounded deterministic noise rule",
            }

        if alert["severity"] in {"fatal", "critical"} or alert["users"] >= 50:
            priority = "P0"
        elif alert["count"] >= 100 or alert["users"] >= 10:
            priority = "P1"
        elif alert["count"] >= 20:
            priority = "P2"
        else:
            priority = "P3"
        alert["priority"] = priority
        return {"alert": alert, "suppressed": False}

    def after_classification(state: AlertState) -> str:
        return "finalize" if state.get("suppressed") else "enrich"

    def enrich(state: AlertState) -> dict[str, Any]:
        alert = state["alert"]
        query = f"{alert['service']} {alert['title']} dependencies runbook impact"
        return {"evidence": dump_evidence(services.knowledge.search(query))}

    def assess(state: AlertState) -> dict[str, Any]:
        decision = services.reasoner.assess_alert(
            state["alert"], load_evidence(state.get("evidence", []))
        )
        return {"decision": decision.model_dump(mode="json")}

    def after_assessment(state: AlertState) -> str:
        decision = state["decision"]
        if decision["status"] == DecisionStatus.SUPPRESS:
            return "finalize"
        if state.get("require_human_review") or decision["status"] == DecisionStatus.REVIEW:
            return "human_review"
        return "recommend"

    def human_review(state: AlertState) -> dict[str, Any]:
        response = interrupt(
            {
                "kind": "alert_review",
                "alert": state["alert"],
                "decision": state["decision"],
                "message": "Approve this alert recommendation?",
            }
        )
        if isinstance(response, bool):
            response = {"approved": response, "actor": "unknown", "reason": "No reason supplied"}
        approval = Approval.model_validate(response)
        return {"approval": approval.model_dump(mode="json")}

    def after_review(state: AlertState) -> str:
        return "recommend" if state["approval"]["approved"] else "finalize"

    def recommend(state: AlertState) -> dict[str, Any]:
        alert = state["alert"]
        decision = state["decision"]
        recommendation = (
            f"{decision['summary']} Investigate {alert['service']} and its documented dependencies; "  # noqa: E501
            "validate current health before any restart or rollback."
        )
        return {"recommendation": recommendation}

    def notify(state: AlertState) -> dict[str, Any]:
        event = load_event(state)
        receipt = services.notifier.send(
            "sre-alerts",
            state["recommendation"],
            idempotency_key=f"{event.idempotency_key}:recommendation",
            run_id=state.get("run_id", event.correlation_id),
        )
        return {"notification_receipt": receipt}

    def finalize(state: AlertState) -> dict[str, Any]:
        if state.get("suppressed"):
            status = "suppressed"
        elif state.get("approval") and not state["approval"]["approved"]:
            status = "rejected"
        elif state.get("notification_receipt"):
            status = "notified"
        else:
            status = "completed"
        return {"status": status}

    builder = StateGraph(AlertState)
    builder.add_node("normalize", normalize)
    builder.add_node("classify", classify)
    builder.add_node("enrich", enrich)
    builder.add_node("assess", assess)
    builder.add_node("human_review", human_review)
    builder.add_node("recommend", recommend)
    builder.add_node("notify", notify)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "normalize")
    builder.add_edge("normalize", "classify")
    builder.add_conditional_edges(
        "classify", after_classification, {"finalize": "finalize", "enrich": "enrich"}
    )
    builder.add_edge("enrich", "assess")
    builder.add_conditional_edges(
        "assess",
        after_assessment,
        {"human_review": "human_review", "recommend": "recommend", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "human_review", after_review, {"recommend": "recommend", "finalize": "finalize"}
    )
    builder.add_edge("recommend", "notify")
    builder.add_edge("notify", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)
