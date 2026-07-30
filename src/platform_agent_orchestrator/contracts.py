"""Cross-domain contracts shared by workflows and adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Self
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
    """Internal trigger accepted by the workflow registry.

    New ingress code must validate an EventEnvelopeV1 and call to_domain_event().
    Existing in-process callers can migrate explicitly through from_legacy().
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: EventType
    source: str
    subject: str
    occurred_at: datetime = Field(default_factory=utc_now)
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    idempotency_key: str
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_legacy(
        cls,
        *,
        type: EventType,
        source: str,
        subject: str,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        **identity: Any,
    ) -> Self:
        """Build an internal event while legacy workflow payloads are migrated."""

        return cls(
            type=type,
            source=source,
            subject=subject,
            idempotency_key=idempotency_key,
            payload=payload or {},
            **identity,
        )

    @model_validator(mode="after")
    def require_non_empty_identity(self) -> DomainEvent:
        if not self.source.strip() or not self.subject.strip() or not self.idempotency_key.strip():
            raise ValueError("source, subject, and idempotency_key must be non-empty")
        return self


class AlertReceivedPayloadV1(BaseModel):
    """Bounded public payload produced by the sample alert service."""

    model_config = ConfigDict(extra="forbid", strict=True)

    alert_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=4_096)
    service: str = Field(min_length=1, max_length=256)
    severity: Literal["info", "warning", "error", "critical", "fatal"]
    environment: str = Field(min_length=1, max_length=128)
    count: int = Field(default=1, ge=1, le=10_000_000)
    users: int = Field(default=0, ge=0, le=10_000_000)

    @model_validator(mode="after")
    def require_trimmed_strings(self) -> Self:
        values = (self.alert_id, self.title, self.service, self.environment)
        if any(not value.strip() or value != value.strip() for value in values):
            raise ValueError("alert string fields must be non-empty and trimmed")
        return self


class EventEnvelopeV1(BaseModel):
    """Strict public transport envelope for the first alert vertical slice."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1"] = "1"
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    type: Literal["alert.received"] = "alert.received"
    source: str = Field(min_length=1, max_length=128)
    subject: str = Field(min_length=1, max_length=256)
    occurred_at: datetime = Field(default_factory=utc_now)
    correlation_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=512)
    payload: AlertReceivedPayloadV1

    @model_validator(mode="after")
    def require_trimmed_identity(self) -> Self:
        values = (self.id, self.source, self.subject, self.correlation_id, self.idempotency_key)
        if any(not value.strip() or value != value.strip() for value in values):
            raise ValueError("event identity fields must be non-empty and trimmed")
        return self

    def to_domain_event(self) -> DomainEvent:
        """Cross the validated transport boundary into serialization-friendly state."""

        return DomainEvent(
            id=self.id,
            type=EventType(self.type),
            source=self.source,
            subject=self.subject,
            occurred_at=self.occurred_at,
            correlation_id=self.correlation_id,
            idempotency_key=self.idempotency_key,
            payload=self.payload.model_dump(mode="json"),
        )


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
