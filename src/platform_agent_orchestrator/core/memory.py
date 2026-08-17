"""Provider-neutral memory data contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MemoryQuery(BaseModel):
    """A bounded recall query within an application-defined scope."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    scope: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] = Field(default_factory=dict)


class MemoryItem(BaseModel):
    """A bounded memory recalled from any configured provider."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRecord(BaseModel):
    """A selective, idempotent memory write."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    scope: str | None = Field(default=None, min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
