"""Domain-neutral event envelope used for flow resolution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DomainEvent(BaseModel):
    """An immutable, namespaced event delivered to one or more flows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    source: str = Field(min_length=1)
    occurred_at: datetime
    correlation_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    subject: str | None = None
    tenant_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
