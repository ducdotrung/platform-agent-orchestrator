"""No-op backend used unless observability is explicitly enabled."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from platform_agent_orchestrator.core.events import DomainEvent

from .base import ScoreDataType, ScoreValue, WorkflowTrace, workflow_metadata, workflow_tags


class NoOpObservability:
    @contextmanager
    def trace_workflow(self, workflow: str, event: DomainEvent) -> Iterator[WorkflowTrace]:
        yield WorkflowTrace(
            tags=workflow_tags(workflow, event),
            metadata=workflow_metadata(workflow, event),
        )

    def score(
        self,
        trace_id: str,
        name: str,
        value: ScoreValue,
        *,
        data_type: ScoreDataType | None = None,
        comment: str | None = None,
    ) -> None:
        return None

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None
