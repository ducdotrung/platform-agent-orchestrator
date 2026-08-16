"""Runtime-neutral node execution contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
