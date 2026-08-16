"""Generic capability invocation contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CapabilityRequest(BaseModel):
    """A provider-neutral request routed by a namespaced capability."""

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(min_length=1)
    operation: str = Field(default="invoke", min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class CapabilityResult(BaseModel):
    """A serializable capability invocation result."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
