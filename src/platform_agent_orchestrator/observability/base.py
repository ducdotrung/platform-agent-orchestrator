"""Small observability boundary for orchestration execution."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from platform_agent_orchestrator.core.events import DomainEvent

ScoreDataType = Literal["NUMERIC", "BOOLEAN", "CATEGORICAL"]
ScoreValue = float | str | bool


@dataclass
class WorkflowTrace:
    """Per-invocation trace hooks without coupling orchestration to a vendor SDK."""

    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None

    def complete(self, result: dict[str, Any]) -> None:
        """Record a successful or interrupted workflow result."""

    def fail(self, error: BaseException) -> None:
        """Record a workflow failure without exporting the exception message."""

    def score(
        self,
        name: str,
        value: ScoreValue,
        *,
        data_type: ScoreDataType | None = None,
        comment: str | None = None,
    ) -> None:
        """Attach an evaluation score to this workflow trace."""


class ObservabilityBackend(Protocol):
    """Vendor-neutral lifecycle used by long-lived workers and short-lived CLIs."""

    def trace_workflow(
        self, workflow: str, event: DomainEvent
    ) -> AbstractContextManager[WorkflowTrace]: ...

    def score(
        self,
        trace_id: str,
        name: str,
        value: ScoreValue,
        *,
        data_type: ScoreDataType | None = None,
        comment: str | None = None,
    ) -> None: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


def workflow_metadata(
    workflow: str, event: DomainEvent
) -> dict[str, str | None]:
    """Return bounded identifiers; payloads and idempotency keys are excluded."""

    return {
        "workflow": workflow,
        "event_id": event.id,
        "event_type": event.type,
        "event_source": event.source,
        "event_subject": event.subject,
        "correlation_id": event.correlation_id,
    }


def workflow_tags(workflow: str, event: DomainEvent) -> list[str]:
    return [f"workflow:{workflow}", f"source:{event.source}"]


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Summarize workflow state without exporting events, evidence, or artifacts."""

    summary: dict[str, Any] = {
        "status": result.get("status", "interrupted" if "__interrupt__" in result else "completed"),
        "interrupted": "__interrupt__" in result,
        "evidence_count": len(result.get("evidence", [])),
        "artifact_count": len(result.get("artifacts", [])),
    }
    for key in ("suppressed", "verified", "risk", "role", "snapshot_id"):
        if key in result:
            summary[key] = result[key]
    decision = result.get("decision")
    if isinstance(decision, dict):
        summary["decision_status"] = decision.get("status")
        summary["decision_confidence"] = decision.get("confidence")
    return summary
