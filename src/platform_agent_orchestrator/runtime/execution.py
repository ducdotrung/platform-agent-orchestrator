"""Serializable workflow execution results."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from platform_agent_orchestrator.sdk.nodes import PauseRequest


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunResult(BaseModel):
    """Provider- and runtime-neutral result of starting or resuming a flow."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    flow: str = Field(min_length=1)
    status: RunStatus
    output: dict[str, Any] = Field(default_factory=dict)
    pause: PauseRequest | None = None
    error: str | None = None
