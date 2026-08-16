"""Bounded evidence and knowledge contracts used across provider boundaries."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceRef(BaseModel):
    """A compact, revision-aware reference to supporting evidence."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    revision: str | None = None
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeArtifact(BaseModel):
    """A provider-neutral knowledge artifact with explicit provenance."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    content: dict[str, Any]
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
