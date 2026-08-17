"""Runtime-neutral alert analysis flow."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, cast

from platform_agent_orchestrator.core.capabilities import CapabilityRequest, CapabilityResult
from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.models import EvidenceRef
from platform_agent_orchestrator.ports.memory import MemoryItem
from platform_agent_orchestrator.sdk.flow import (
    FLOW_END,
    BaseFlow,
    ConditionalRoute,
    EdgeSpec,
    FlowDefinition,
    FlowMetadata,
    NodeSpec,
)
from platform_agent_orchestrator.sdk.nodes import NodeContext, NodeOutcome, PauseRequest

MIN_AUTOMATED_CONFIDENCE = 0.75


class AlertState(TypedDict, total=False):
    event: dict[str, Any]
    run_id: str
    alert: dict[str, Any]
    classification: dict[str, Any]
    evidence: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    memory_available: bool
    impact: dict[str, Any]
    review_required: bool
    review_status: str
    review: dict[str, Any]
    recommendation: str
    notification_receipt: str
    memory_recorded: bool
    memory_record_error: str
    status: str


class CapabilityAccess(Protocol):
    def has(self, capability: str) -> bool: ...

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult: ...


class AlertFlow(BaseFlow):
    metadata = FlowMetadata(
        name="alert",
        version="2.0.0",
        description="Classify, enrich, review, and notify on monitoring alerts.",
        event_types=frozenset({"monitoring.alert.received"}),
        required_capabilities=frozenset(
            {
                "alert.classify",
                "knowledge.search",
                "knowledge.change_impact",
                "notification.send",
            }
        ),
        optional_capabilities=frozenset({"memory.recall", "memory.record"}),
        tags=frozenset({"builtin", "alert", "sre"}),
    )

    def define(self) -> FlowDefinition:
        return FlowDefinition(
            state_schema=AlertState,
            entrypoint="normalize",
            nodes=[
                NodeSpec("normalize", _normalize),
                NodeSpec("classify", _classify),
                NodeSpec("retrieve_knowledge", _retrieve_knowledge),
                NodeSpec("recall_memory", _recall_memory),
                NodeSpec("assess_impact", _assess_impact),
                NodeSpec("confidence_decision", _confidence_decision),
                NodeSpec("review", _review),
                NodeSpec("recommend", _recommend),
                NodeSpec("notify", _notify),
                NodeSpec("record_memory", _record_memory),
                NodeSpec("finalize", _finalize),
            ],
            edges=[
                EdgeSpec("normalize", "classify"),
                EdgeSpec("retrieve_knowledge", "recall_memory"),
                EdgeSpec("recall_memory", "assess_impact"),
                EdgeSpec("assess_impact", "confidence_decision"),
                EdgeSpec("recommend", "notify"),
                EdgeSpec("notify", "record_memory"),
                EdgeSpec("record_memory", "finalize"),
                EdgeSpec("finalize", FLOW_END),
            ],
            conditional_routes=[
                ConditionalRoute(
                    source="classify",
                    router=_after_classification,
                    routes={"suppressed": "finalize", "enrich": "retrieve_knowledge"},
                ),
                ConditionalRoute(
                    source="confidence_decision",
                    router=_after_confidence_decision,
                    routes={"review": "review", "recommend": "recommend"},
                ),
                ConditionalRoute(
                    source="review",
                    router=_after_review,
                    routes={"recommend": "recommend", "finalize": "finalize"},
                ),
            ],
        )


def _normalize(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    event = state.get("event")
    if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
        raise ValueError("alert flow requires a runtime-neutral event object")
    data = event["data"]
    alert_id = str(data.get("alert_id") or event.get("subject") or "").strip()
    if not alert_id:
        raise ValueError("alert requires an alert_id or event subject")
    return {
        "alert": {
            "id": alert_id,
            "title": str(data.get("title", "Untitled alert")).strip(),
            "service": str(data.get("service", "unknown-service")).strip(),
            "severity": str(data.get("severity", "warning")).strip().lower(),
            "count": _nonnegative_int(data.get("count", 1), "count"),
            "users": _nonnegative_int(data.get("users", 0), "users"),
            "environment": str(data.get("environment", "unknown")).strip(),
        }
    }


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"alert {field} must be an integer")
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"alert {field} must be non-negative")
    return parsed


async def _classify(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="alert.classify",
            operation="classify",
            arguments={"alert": state["alert"]},
        ),
        context=node.execution,
    )
    if not result.success:
        raise RuntimeError(result.error or "alert.classify failed")
    raw = result.data.get("classification")
    if not isinstance(raw, dict) or not isinstance(raw.get("suppressed"), bool):
        raise TypeError("alert.classify returned an invalid classification")
    classification = dict(raw)
    alert = dict(state["alert"])
    if not classification["suppressed"]:
        priority = str(classification.get("priority", "")).strip()
        if not priority:
            raise ValueError("unsuppressed classification requires priority")
        alert["priority"] = priority
    return {"alert": alert, "classification": classification}


def _after_classification(state: dict[str, Any]) -> str:
    return "suppressed" if state["classification"]["suppressed"] else "enrich"


async def _retrieve_knowledge(
    state: dict[str, Any],
    node: NodeContext,
) -> dict[str, Any]:
    alert = state["alert"]
    query = f"{alert['service']} {alert['title']} dependencies runbook impact"
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="knowledge.search",
            operation="search",
            arguments={"query": query, "limit": 8},
        ),
        context=node.execution,
    )
    if not result.success:
        raise RuntimeError(result.error or "knowledge.search failed")
    evidence = _model_items(result.data, "evidence", EvidenceRef)
    return {"evidence": [item.model_dump(mode="json") for item in evidence]}


async def _recall_memory(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    if not capabilities.has("memory.recall"):
        return {"memories": [], "memory_available": False}
    alert = state["alert"]
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="memory.recall",
            operation="recall",
            arguments={
                "query": f"{alert['service']} {alert['title']}",
                "role": "alert",
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


async def _assess_impact(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="knowledge.change_impact",
            operation="assess",
            arguments={
                "alert": state["alert"],
                "classification": state["classification"],
                "evidence": state.get("evidence", []),
                "memories": state.get("memories", []),
            },
        ),
        context=node.execution,
    )
    if not result.success:
        raise RuntimeError(result.error or "knowledge.change_impact failed")
    raw = result.data.get("impact")
    if not isinstance(raw, dict):
        raise TypeError("knowledge.change_impact returned an invalid impact")
    impact = dict(raw)
    summary = str(impact.get("summary", "")).strip()
    confidence = impact.get("confidence")
    if not summary:
        raise ValueError("impact summary must be non-empty")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        raise ValueError("impact confidence must be between zero and one")
    impact["summary"] = summary
    impact["confidence"] = float(confidence)
    impact["requires_review"] = impact.get("requires_review") is True
    impact["memory_worthy"] = impact.get("memory_worthy") is True
    return {"impact": impact}


def _confidence_decision(
    state: dict[str, Any],
    _node: NodeContext,
) -> dict[str, Any]:
    impact = state["impact"]
    review_required = (
        impact["confidence"] < MIN_AUTOMATED_CONFIDENCE
        or impact["requires_review"]
        or state["classification"].get("requires_review") is True
    )
    return {"review_required": review_required}


def _after_confidence_decision(state: dict[str, Any]) -> str:
    return "review" if state["review_required"] else "recommend"


def _review(state: dict[str, Any], node: NodeContext) -> NodeOutcome | dict[str, Any]:
    if node.resume_payload is None:
        alert = state["alert"]
        impact = state["impact"]
        return NodeOutcome(
            updates={"review_status": "pending"},
            pause=PauseRequest(
                reason="Low-confidence alert recommendation requires human review",
                approval_id=f"alert-review:{state['event']['id']}",
                payload={
                    "kind": "alert_review",
                    "alert_id": alert["id"],
                    "service": alert["service"],
                    "impact_summary": impact["summary"],
                    "confidence": impact["confidence"],
                },
            ),
        )
    approved = node.resume_payload.get("approved")
    if not isinstance(approved, bool):
        raise ValueError("alert review resume requires an approved boolean")
    return {
        "review_status": "approved" if approved else "rejected",
        "review": {
            "approved": approved,
            "actor": str(node.resume_payload.get("actor", "unknown")),
            "reason": str(node.resume_payload.get("reason", "No reason supplied")),
        },
    }


def _after_review(state: dict[str, Any]) -> str:
    return "recommend" if state["review"]["approved"] else "finalize"


def _recommend(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    provided = str(state["impact"].get("recommendation", "")).strip()
    if provided:
        return {"recommendation": provided}
    alert = state["alert"]
    return {
        "recommendation": (
            f"{state['impact']['summary']} Investigate {alert['service']} and its "
            "documented dependencies; validate current health before mutation."
        )
    }


async def _notify(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    event = state["event"]
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="notification.send",
            operation="send",
            arguments={
                "channel": "sre-alerts",
                "message": state["recommendation"],
                "idempotency_key": f"{event['idempotency_key']}:recommendation",
            },
        ),
        context=node.execution,
    )
    if not result.success:
        raise RuntimeError(result.error or "notification.send failed")
    receipt = str(result.data.get("receipt", "")).strip()
    if not receipt:
        raise RuntimeError("notification.send returned no receipt")
    return {"notification_receipt": receipt}


async def _record_memory(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    if not state["impact"]["memory_worthy"] or not capabilities.has("memory.record"):
        return {"memory_recorded": False}
    event = state["event"]
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="memory.record",
            operation="record",
            arguments={
                "idempotency_key": f"{event['idempotency_key']}:memory",
                "subject": state["alert"]["service"],
                "revision": str(event.get("id", "unknown")),
                "snapshot_id": state["notification_receipt"],
                "summary": state["impact"]["summary"],
            },
        ),
        context=node.execution,
    )
    if not result.success:
        return {
            "memory_recorded": False,
            "memory_record_error": result.error or "memory.record failed",
        }
    return {"memory_recorded": True}


def _finalize(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    if state.get("classification", {}).get("suppressed"):
        status = "suppressed"
    elif state.get("review", {}).get("approved") is False:
        status = "rejected"
    elif state.get("notification_receipt"):
        status = "notified"
    else:
        status = "completed"
    return {"status": status}


def _model_items(data: dict[str, Any], key: str, model: type[Any]) -> list[Any]:
    raw_items = data.get(key, [])
    if not isinstance(raw_items, list):
        raise TypeError(f"capability result {key} must be a list")
    return [model.model_validate(item) for item in raw_items]
