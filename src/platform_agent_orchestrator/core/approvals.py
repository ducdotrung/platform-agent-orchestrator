"""Runtime-neutral approval requests, decisions, and action binding."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .actions import ActionIntent
from .context import ExecutionIdentity
from .errors import (
    ApprovalActionMismatchError,
    ApprovalBindingError,
    ApprovalIdentityMismatchError,
    ApprovalRejectedError,
)

_ACTION_HASH_PATTERN = r"^[0-9a-f]{64}$"
_ACTION_HASH_SCHEMA = "platform-agent/action-intent/v1"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def compute_action_hash(action: ActionIntent) -> str:
    """Return a deterministic fingerprint of the complete action intent."""

    canonical = json.dumps(
        {
            "schema": _ACTION_HASH_SCHEMA,
            "action": action.model_dump(mode="json"),
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


class ApprovalRequest(BaseModel):
    """Pending approval bound to an action and execution identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1, max_length=128)
    action_hash: str = Field(pattern=_ACTION_HASH_PATTERN)
    policy_version: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2_048)
    requested_at: datetime = Field(default_factory=_utc_now)
    run_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    tenant_id: str | None = Field(default=None, max_length=128)

    @field_validator("requested_at")
    @classmethod
    def require_aware_requested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        return value

    @classmethod
    def for_action(
        cls,
        action: ActionIntent,
        *,
        identity: ExecutionIdentity,
        approval_id: str,
        policy_version: str,
        reason: str,
        requested_at: datetime | None = None,
    ) -> Self:
        """Build an approval request without embedding action arguments."""

        values = {
            "approval_id": approval_id,
            "action_hash": compute_action_hash(action),
            "policy_version": policy_version,
            "reason": reason,
            "run_id": identity.run_id,
            "thread_id": identity.thread_id,
            "correlation_id": identity.correlation_id,
            "tenant_id": identity.tenant_id,
        }
        if requested_at is not None:
            values["requested_at"] = requested_at
        return cls.model_validate(values)


class ApprovalBinding(BaseModel):
    """Human decision bound to the exact requested action and run identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1, max_length=128)
    approved: bool
    actor: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=2_048)
    decided_at: datetime = Field(default_factory=_utc_now)
    action_hash: str = Field(pattern=_ACTION_HASH_PATTERN)
    policy_version: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    tenant_id: str | None = Field(default=None, max_length=128)

    @field_validator("decided_at")
    @classmethod
    def require_aware_decided_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decided_at must be timezone-aware")
        return value


def _identity_values(identity: ExecutionIdentity) -> tuple[str, str, str, str | None]:
    return (
        identity.run_id,
        identity.thread_id,
        identity.correlation_id,
        identity.tenant_id,
    )


def validate_approval_binding(
    approval: ApprovalBinding,
    *,
    request: ApprovalRequest,
    action: ActionIntent,
    identity: ExecutionIdentity,
) -> ApprovalBinding:
    """Validate an approval before allowing the bound action to execute."""

    if not approval.approved:
        raise ApprovalRejectedError("approval decision rejected the action")

    expected_hash = compute_action_hash(action)
    if not (
        hmac.compare_digest(request.action_hash, expected_hash)
        and hmac.compare_digest(approval.action_hash, expected_hash)
    ):
        raise ApprovalActionMismatchError("approval does not match the current action")

    request_identity = (
        request.run_id,
        request.thread_id,
        request.correlation_id,
        request.tenant_id,
    )
    approval_identity = (
        approval.run_id,
        approval.thread_id,
        approval.correlation_id,
        approval.tenant_id,
    )
    if request_identity != _identity_values(identity) or approval_identity != request_identity:
        raise ApprovalIdentityMismatchError("approval does not match the execution identity")

    if approval.approval_id != request.approval_id:
        raise ApprovalIdentityMismatchError("approval identifier does not match the request")
    if approval.policy_version != request.policy_version:
        raise ApprovalBindingError("approval policy version does not match the request")
    if approval.decided_at < request.requested_at:
        raise ApprovalBindingError("approval decision predates the request")
    return approval
