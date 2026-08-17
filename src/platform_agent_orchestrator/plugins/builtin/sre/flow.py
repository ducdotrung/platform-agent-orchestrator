"""Runtime-neutral, policy-gated SRE execution flow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict, cast

from platform_agent_orchestrator.core import (
    ActionIntent,
    ActionResult,
    ApprovalBinding,
    ApprovalRequest,
    CapabilityRequest,
    CapabilityResult,
    ExecutionContext,
    ExecutionIdentity,
    RiskLevel,
    compute_action_hash,
    validate_approval_binding,
)
from platform_agent_orchestrator.policy import PolicyDecision
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

_READ_ONLY_OPERATIONS = frozenset({"inspect", "logs", "status", "describe", "get", "list"})


class SREState(TypedDict, total=False):
    event: dict[str, Any]
    run_id: str
    ticket: dict[str, Any]
    evidence: list[dict[str, Any]]
    memories: list[dict[str, Any]]
    memory_available: bool
    action: dict[str, Any]
    action_hash: str
    policy_decision: dict[str, Any]
    approval_request: dict[str, Any]
    approval: dict[str, Any]
    approval_status: str
    execution_attempted: bool
    execution_result: dict[str, Any]
    execution_error: str
    verified: bool
    verification_error: str
    outcome_known: bool
    outcome: dict[str, Any]
    notification_receipt: str
    notification_error: str
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


class PolicyAccess(Protocol):
    @property
    def version(self) -> str: ...

    async def evaluate(
        self,
        action: ActionIntent,
        *,
        context: ExecutionContext,
    ) -> PolicyDecision: ...

    def create_approval_request(
        self,
        action: ActionIntent,
        decision: PolicyDecision,
        *,
        identity: ExecutionIdentity,
        approval_id: str,
    ) -> ApprovalRequest: ...


class SREFlow(BaseFlow):
    metadata = FlowMetadata(
        name="sre",
        version="2.0.0",
        description="Execute bounded SRE actions through policy and framework approval.",
        event_types=frozenset({"sre.ticket.updated", "sre.action.requested"}),
        required_capabilities=frozenset({"infra.execute", "infra.verify"}),
        optional_capabilities=frozenset(
            {"knowledge.search", "memory.recall", "memory.record", "notification.send"}
        ),
        tags=frozenset({"builtin", "sre", "policy", "approval"}),
    )

    def define(self) -> FlowDefinition:
        return FlowDefinition(
            state_schema=SREState,
            entrypoint="normalize",
            nodes=[
                NodeSpec("normalize", _normalize),
                NodeSpec("retrieve_knowledge", _retrieve_knowledge),
                NodeSpec("recall_memory", _recall_memory),
                NodeSpec("create_action", _create_action),
                NodeSpec("evaluate_policy", _evaluate_policy),
                NodeSpec("approval", _approval),
                NodeSpec("policy_denied", _policy_denied),
                NodeSpec("approval_rejected", _approval_rejected),
                NodeSpec("execute", _execute),
                NodeSpec("execution_failed", _execution_failed),
                NodeSpec("verify", _verify),
                NodeSpec("verification_failed", _verification_failed),
                NodeSpec("verified", _verified),
                NodeSpec("notify", _notify),
                NodeSpec("record_memory", _record_memory),
                NodeSpec("finalize", _finalize),
            ],
            edges=[
                EdgeSpec("normalize", "retrieve_knowledge"),
                EdgeSpec("retrieve_knowledge", "recall_memory"),
                EdgeSpec("recall_memory", "create_action"),
                EdgeSpec("create_action", "evaluate_policy"),
                EdgeSpec("policy_denied", "notify"),
                EdgeSpec("approval_rejected", "notify"),
                EdgeSpec("execution_failed", "notify"),
                EdgeSpec("verification_failed", "notify"),
                EdgeSpec("verified", "notify"),
                EdgeSpec("notify", "record_memory"),
                EdgeSpec("record_memory", "finalize"),
                EdgeSpec("finalize", FLOW_END),
            ],
            conditional_routes=[
                ConditionalRoute(
                    source="evaluate_policy",
                    router=_after_policy,
                    routes={
                        "allow": "execute",
                        "deny": "policy_denied",
                        "require_approval": "approval",
                    },
                ),
                ConditionalRoute(
                    source="approval",
                    router=_after_approval,
                    routes={"execute": "execute", "rejected": "approval_rejected"},
                ),
                ConditionalRoute(
                    source="execute",
                    router=_after_execution,
                    routes={"verify": "verify", "failed": "execution_failed"},
                ),
                ConditionalRoute(
                    source="verify",
                    router=_after_verification,
                    routes={"verified": "verified", "failed": "verification_failed"},
                ),
            ],
        )


def _normalize(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    event = state.get("event")
    if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
        raise ValueError("SRE flow requires a runtime-neutral event object")
    data = event["data"]
    key = str(data.get("key") or event.get("subject") or "").strip()
    service = str(data.get("service", "")).strip()
    operation = str(data.get("operation", "inspect")).strip().lower()
    if not key or not service or not operation:
        raise ValueError("SRE action requires key, service, and operation")
    arguments = data.get("arguments", {})
    if not isinstance(arguments, dict):
        raise TypeError("SRE action arguments must be an object")
    resource = str(data.get("resource") or f"service/{service}").strip()
    if not resource:
        raise ValueError("SRE action resource must be non-empty")
    return {
        "ticket": {
            "key": key,
            "summary": str(data.get("summary", "SRE action request")).strip(),
            "service": service,
            "environment": str(data.get("environment", "dev")).strip(),
            "operation": operation,
            "resource": resource,
            "arguments": dict(arguments),
        }
    }


async def _retrieve_knowledge(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    if not capabilities.has("knowledge.search"):
        return {"evidence": []}
    ticket = state["ticket"]
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="knowledge.search",
            operation="search",
            arguments={
                "query": (
                    f"{ticket['service']} {ticket['environment']} {ticket['operation']} "
                    "runbook rollback dependencies"
                ),
                "limit": 8,
            },
        ),
        context=node.execution,
    )
    if not result.success:
        return {"evidence": []}
    raw = result.data.get("evidence", []) if isinstance(result.data, dict) else []
    if not isinstance(raw, list):
        raise TypeError("knowledge.search evidence must be a list")
    return {"evidence": [dict(item) for item in raw if isinstance(item, dict)]}


async def _recall_memory(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    if not capabilities.has("memory.recall"):
        return {"memories": [], "memory_available": False}
    ticket = state["ticket"]
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="memory.recall",
            operation="recall",
            arguments={
                "query": f"{ticket['service']} {ticket['environment']} {ticket['operation']}",
                "role": "sre",
                "limit": 5,
            },
        ),
        context=node.execution,
    )
    if not result.success:
        return {"memories": [], "memory_available": False}
    raw = result.data.get("memories", []) if isinstance(result.data, dict) else []
    if not isinstance(raw, list):
        raise TypeError("memory.recall memories must be a list")
    return {
        "memories": [dict(item) for item in raw if isinstance(item, dict)],
        "memory_available": True,
    }


def _create_action(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    ticket = state["ticket"]
    event = state["event"]
    operation = ticket["operation"]
    requested_risk = (
        RiskLevel.READ_ONLY if operation in _READ_ONLY_OPERATIONS else RiskLevel.RISKY
    )
    action = ActionIntent(
        capability="infra.execute",
        operation=operation,
        resource=ticket["resource"],
        arguments={**ticket["arguments"], "environment": ticket["environment"]},
        requested_risk=requested_risk,
        idempotency_key=f"{event['idempotency_key']}:infra:{operation}",
        metadata={"ticket_key": ticket["key"]},
    )
    return {
        "action": action.model_dump(mode="json"),
        "action_hash": compute_action_hash(action),
    }


async def _evaluate_policy(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    action = ActionIntent.model_validate(state["action"])
    policy = cast(PolicyAccess, node.execution.policy)
    decision = await policy.evaluate(action, context=node.execution)
    updates: dict[str, Any] = {"policy_decision": decision.model_dump(mode="json")}
    if decision.outcome == "require_approval":
        request = policy.create_approval_request(
            action,
            decision,
            identity=node.execution.identity,
            approval_id=f"sre-action:{compute_action_hash(action)[:32]}",
        )
        updates["approval_request"] = request.model_dump(mode="json")
    return updates


def _after_policy(state: dict[str, Any]) -> str:
    return str(state["policy_decision"]["outcome"])


def _approval(state: dict[str, Any], node: NodeContext) -> NodeOutcome | dict[str, Any]:
    action = ActionIntent.model_validate(state["action"])
    request = ApprovalRequest.model_validate(state["approval_request"])
    if node.resume_payload is None:
        return NodeOutcome(
            updates={"approval_status": "pending"},
            pause=PauseRequest.for_approval(
                request,
                payload={
                    "kind": "sre_action_approval",
                    "ticket_key": state["ticket"]["key"],
                    "operation": action.operation,
                    "resource": action.resource,
                    "action_hash": request.action_hash,
                    "policy_version": request.policy_version,
                },
            ),
        )

    binding = _approval_binding(node.resume_payload, request)
    if binding.approved:
        validate_approval_binding(
            binding,
            request=request,
            action=action,
            identity=node.execution.identity,
        )
    return {
        "approval": binding.model_dump(mode="json"),
        "approval_status": "approved" if binding.approved else "rejected",
    }


def _approval_binding(
    payload: object,
    request: ApprovalRequest,
) -> ApprovalBinding:
    if not isinstance(payload, dict):
        raise TypeError("SRE approval resume payload must be an object")
    approved = payload.get("approved")
    if not isinstance(approved, bool):
        raise ValueError("SRE approval resume requires an approved boolean")
    values = {
        "approval_id": request.approval_id,
        "approved": approved,
        "actor": str(payload.get("actor", "unknown")),
        "reason": str(payload.get("reason", "No reason supplied")),
        "decided_at": payload.get("decided_at", datetime.now(UTC)),
        "action_hash": request.action_hash,
        "policy_version": request.policy_version,
        "run_id": request.run_id,
        "thread_id": request.thread_id,
        "correlation_id": request.correlation_id,
        "tenant_id": request.tenant_id,
    }
    for field in (
        "approval_id",
        "action_hash",
        "policy_version",
        "run_id",
        "thread_id",
        "correlation_id",
        "tenant_id",
    ):
        if field in payload:
            values[field] = payload[field]
    return ApprovalBinding.model_validate(values)


def _after_approval(state: dict[str, Any]) -> str:
    return "execute" if state["approval"]["approved"] else "rejected"


async def _execute(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    action = ActionIntent.model_validate(state["action"])
    decision = PolicyDecision.model_validate(state["policy_decision"])
    if decision.outcome == "deny":
        raise PermissionError("policy denied action reached execution")
    if decision.outcome == "require_approval":
        request = ApprovalRequest.model_validate(state["approval_request"])
        binding = ApprovalBinding.model_validate(state["approval"])
        validate_approval_binding(
            binding,
            request=request,
            action=action,
            identity=node.execution.identity,
        )

    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="infra.execute",
            operation="execute",
            arguments={
                "action": action.model_dump(mode="json"),
                "action_hash": compute_action_hash(action),
            },
        ),
        context=node.execution,
    )
    if not result.success:
        action_result = ActionResult(
            success=False,
            status="execution_failed",
            error=result.error or "infra.execute failed",
        )
    else:
        raw = result.data.get("result") if isinstance(result.data, dict) else None
        try:
            action_result = ActionResult.model_validate(raw)
        except (TypeError, ValueError) as error:
            action_result = ActionResult(
                success=False,
                status="invalid_execution_result",
                error=str(error),
            )
    updates: dict[str, Any] = {
        "execution_attempted": True,
        "execution_result": action_result.model_dump(mode="json"),
    }
    if not action_result.success:
        updates["execution_error"] = action_result.error or action_result.status
    return updates


def _after_execution(state: dict[str, Any]) -> str:
    return "verify" if state["execution_result"]["success"] else "failed"


async def _verify(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    action = ActionIntent.model_validate(state["action"])
    result = ActionResult.model_validate(state["execution_result"])
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    verification = await capabilities.invoke(
        CapabilityRequest(
            capability="infra.verify",
            operation="verify",
            arguments={
                "action": action.model_dump(mode="json"),
                "action_hash": compute_action_hash(action),
                "execution_result": result.model_dump(mode="json"),
            },
        ),
        context=node.execution,
    )
    if not verification.success:
        return {
            "verified": False,
            "verification_error": verification.error or "infra.verify failed",
        }
    raw_verified = (
        verification.data.get("verified") if isinstance(verification.data, dict) else None
    )
    if not isinstance(raw_verified, bool):
        return {"verified": False, "verification_error": "invalid verification result"}
    updates: dict[str, Any] = {"verified": raw_verified}
    if not raw_verified:
        updates["verification_error"] = str(
            verification.data.get("reason", "infrastructure verification failed")
        )
    return updates


def _after_verification(state: dict[str, Any]) -> str:
    return "verified" if state["verified"] else "failed"


def _policy_denied(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    return _known_outcome(
        state,
        status="policy_denied",
        phase="policy",
        detail=state["policy_decision"]["reason"],
    )


def _approval_rejected(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    return _known_outcome(
        state,
        status="approval_rejected",
        phase="approval",
        detail=state["approval"]["reason"],
    )


def _execution_failed(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    return _known_outcome(
        state,
        status="execution_failed",
        phase="execution",
        detail=state.get("execution_error", "infrastructure execution failed"),
    )


def _verification_failed(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    return _known_outcome(
        state,
        status="verification_failed",
        phase="verification",
        detail=state.get("verification_error", "infrastructure verification failed"),
    )


def _verified(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    return _known_outcome(
        state,
        status="completed",
        phase="verification",
        detail="Infrastructure action completed and verification passed",
    )


def _known_outcome(
    state: dict[str, Any],
    *,
    status: str,
    phase: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "outcome_known": True,
        "status": status,
        "outcome": {
            "status": status,
            "phase": phase,
            "detail": detail,
            "ticket_key": state["ticket"]["key"],
            "action_hash": state["action_hash"],
        },
    }


async def _notify(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    if not capabilities.has("notification.send"):
        return {}
    outcome = state["outcome"]
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="notification.send",
            operation="send",
            arguments={
                "channel": "sre-operations",
                "message": (
                    f"{state['ticket']['key']} {outcome['status']} during "
                    f"{outcome['phase']}: {outcome['detail']}"
                ),
                "idempotency_key": f"{state['event']['idempotency_key']}:sre-outcome",
                "audit": {
                    "ticket_key": state["ticket"]["key"],
                    "action_hash": state["action_hash"],
                    "status": outcome["status"],
                    "phase": outcome["phase"],
                },
            },
        ),
        context=node.execution,
    )
    if not result.success:
        return {"notification_error": result.error or "notification.send failed"}
    receipt = result.data.get("receipt") if isinstance(result.data, dict) else None
    return {"notification_receipt": str(receipt or "")}


async def _record_memory(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    if not state.get("outcome_known"):
        raise RuntimeError("operational memory cannot be written before outcome is known")
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    if not state.get("execution_attempted") or not capabilities.has("memory.record"):
        return {"memory_recorded": False}
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="memory.record",
            operation="record",
            arguments={
                "subject": state["ticket"]["key"],
                "revision": state["event"]["id"],
                "snapshot_id": state["action_hash"],
                "content": {
                    "service": state["ticket"]["service"],
                    "environment": state["ticket"]["environment"],
                    "operation": state["ticket"]["operation"],
                    "outcome": state["outcome"],
                },
                "idempotency_key": f"{state['event']['idempotency_key']}:sre-memory",
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
    if not state.get("outcome_known"):
        raise RuntimeError("SRE flow ended before outcome was known")
    return {"status": state["outcome"]["status"]}
