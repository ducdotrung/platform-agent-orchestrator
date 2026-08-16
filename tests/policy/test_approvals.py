from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.core import (
    ApprovalActionMismatchError,
    ApprovalBinding,
    ApprovalIdentityMismatchError,
    ApprovalRequest,
    RiskLevel,
    compute_action_hash,
    validate_approval_binding,
)
from platform_agent_orchestrator.sdk import PauseRequest

from .helpers import action, identity

NOW = datetime(2026, 8, 16, tzinfo=UTC)


def approval_request() -> ApprovalRequest:
    return ApprovalRequest.for_action(
        action(RiskLevel.RISKY),
        identity=identity(),
        approval_id="approval-1",
        policy_version="default-v1",
        reason="Risky action requires approval",
        requested_at=NOW,
    )


def approval_binding(request: ApprovalRequest, **changes: object) -> ApprovalBinding:
    values: dict[str, object] = {
        "approval_id": request.approval_id,
        "approved": True,
        "actor": "reviewer@example.com",
        "reason": "Reviewed the exact bounded action",
        "decided_at": NOW + timedelta(minutes=1),
        "action_hash": request.action_hash,
        "policy_version": request.policy_version,
        "run_id": request.run_id,
        "thread_id": request.thread_id,
        "correlation_id": request.correlation_id,
        "tenant_id": request.tenant_id,
    }
    values.update(changes)
    return ApprovalBinding.model_validate(values)


def test_action_hash_is_canonical_and_covers_complete_intent() -> None:
    first = action(RiskLevel.RISKY, arguments={"replicas": 2, "zone": "a"})
    reordered = action(RiskLevel.RISKY, arguments={"zone": "a", "replicas": 2})
    modified = action(RiskLevel.RISKY, arguments={"replicas": 3, "zone": "a"})

    assert compute_action_hash(first) == compute_action_hash(reordered)
    assert compute_action_hash(first) != compute_action_hash(modified)


def test_valid_approval_is_bound_to_action_and_execution_identity() -> None:
    request = approval_request()
    binding = approval_binding(request)

    assert (
        validate_approval_binding(
            binding,
            request=request,
            action=action(RiskLevel.RISKY),
            identity=identity(),
        )
        is binding
    )


def test_modified_action_after_approval_invalidates_action_hash() -> None:
    request = approval_request()

    with pytest.raises(ApprovalActionMismatchError):
        validate_approval_binding(
            approval_binding(request),
            request=request,
            action=action(RiskLevel.RISKY, arguments={"replicas": 99}),
            identity=identity(),
        )


def test_approval_from_another_run_is_rejected() -> None:
    request = approval_request()

    with pytest.raises(ApprovalIdentityMismatchError):
        validate_approval_binding(
            approval_binding(request),
            request=request,
            action=action(RiskLevel.RISKY),
            identity=identity(run_id="run-2"),
        )


def test_pause_request_carries_typed_approval_binding_without_action_arguments() -> None:
    request = approval_request()
    pause = PauseRequest.for_approval(request, payload={"resource": "service/orders"})

    assert pause.approval == request
    assert pause.approval_id == "approval-1"
    assert "arguments" not in pause.model_dump(mode="json")["approval"]


def test_pause_request_rejects_mismatched_approval_identifier() -> None:
    with pytest.raises(ValidationError):
        PauseRequest(
            reason="Review",
            approval_id="different",
            approval=approval_request(),
        )
