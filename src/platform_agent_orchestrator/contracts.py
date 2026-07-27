"""Cross-domain contracts shared by workflows and adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class EventType(StrEnum):
    ALERT_RECEIVED = "alert.received"
    PR_MERGED = "scm.pull_request.merged"
    SRE_TICKET_UPDATED = "sre.ticket.updated"
    ENGINEERING_QUESTION = "engineering.question"


class RiskLevel(StrEnum):
    SAFE = "safe"
    CAUTION = "caution"
    RISKY = "risky"


class DecisionStatus(StrEnum):
    SUPPRESS = "suppress"
    PROCEED = "proceed"
    REVIEW = "review"
    REJECT = "reject"


class EvidenceKind(StrEnum):
    CODE = "code"
    CONFIG = "config"
    DOCUMENT = "document"
    GRAPH = "graph"
    ALERT = "alert"
    HUMAN = "human"


class DomainEvent(BaseModel):
    """Immutable trigger accepted by the workflow registry."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: EventType
    source: str
    subject: str
    occurred_at: datetime = Field(default_factory=utc_now)
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    idempotency_key: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_non_empty_identity(self) -> DomainEvent:
        if not self.source.strip() or not self.subject.strip() or not self.idempotency_key.strip():
            raise ValueError("source, subject, and idempotency_key must be non-empty")
        return self


class EvidenceRef(BaseModel):
    """A bounded, revision-aware pointer supporting a claim."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: EvidenceKind
    source: str
    locator: str
    revision: str | None = None
    summary: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    observed_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeArtifact(BaseModel):
    """Revisioned knowledge output published by a refresh workflow."""

    id: str
    artifact_type: str
    subject: str
    revision: str
    content: dict[str, Any]
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    schema_version: str = "1"


class AgentDecision(BaseModel):
    status: DecisionStatus
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class Approval(BaseModel):
    approved: bool
    actor: str
    reason: str
    decided_at: datetime = Field(default_factory=utc_now)


class ActionRequest(BaseModel):
    action: str
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk: RiskLevel
    idempotency_key: str


class ActionResult(BaseModel):
    request: ActionRequest
    success: bool
    summary: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=utc_now)
