"""Provider-neutral action intent and result contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(StrEnum):
    """Risk classification used by policy implementations."""

    READ_ONLY = "read_only"
    SAFE = "safe"
    CAUTION = "caution"
    RISKY = "risky"


class ActionIntent(BaseModel):
    """A bounded request for a capability provider to mutate or inspect a resource."""

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    resource: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    requested_risk: RiskLevel | None = None
    idempotency_key: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Serializable outcome returned by an action provider."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    status: str = Field(min_length=1)
    output: dict[str, Any] = Field(default_factory=dict)
    receipt_id: str | None = None
    error: str | None = None
