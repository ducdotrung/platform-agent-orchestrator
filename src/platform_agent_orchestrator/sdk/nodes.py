"""Runtime-neutral node execution contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from platform_agent_orchestrator.core.approvals import ApprovalRequest
from platform_agent_orchestrator.core.context import ExecutionContext


@dataclass(frozen=True)
class NodeContext:
    """Runtime-owned services and metadata supplied to a node handler."""

    execution: ExecutionContext
    node_name: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    resume_payload: Mapping[str, Any] | None = None


class PauseRequest(BaseModel):
    """Framework request to pause a run for external input or approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    approval_id: str = Field(min_length=1)
    approval: ApprovalRequest | None = None

    @model_validator(mode="after")
    def bind_typed_approval(self) -> PauseRequest:
        if self.approval is not None and self.approval.approval_id != self.approval_id:
            raise ValueError("pause approval_id must match the approval request")
        return self

    @classmethod
    def for_approval(
        cls,
        approval: ApprovalRequest,
        *,
        payload: dict[str, Any] | None = None,
    ) -> PauseRequest:
        """Create a pause carrying a typed action approval request."""

        return cls(
            reason=approval.reason,
            approval_id=approval.approval_id,
            approval=approval,
            payload=payload or {},
        )


class NodeOutcome(BaseModel):
    """State updates and an optional runtime-neutral pause request."""

    model_config = ConfigDict(extra="forbid")

    updates: dict[str, Any] = Field(default_factory=dict)
    pause: PauseRequest | None = None


class PauseExecution(Exception):
    """Optional control flow for runtimes that cannot propagate NodeOutcome directly."""

    def __init__(self, request: PauseRequest) -> None:
        self.request = request
        super().__init__(request.reason)
