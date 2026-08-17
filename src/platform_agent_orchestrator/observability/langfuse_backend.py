"""Langfuse implementation of the observability boundary."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler

from platform_agent_orchestrator.core.events import DomainEvent

from .base import (
    ScoreDataType,
    ScoreValue,
    WorkflowTrace,
    result_summary,
    workflow_metadata,
    workflow_tags,
)
from .masking import build_otel_masker, redact_text, redact_value
from .settings import ObservabilitySettings


class LangfuseWorkflowTrace(WorkflowTrace):
    def __init__(
        self, *, span: Any, callbacks: list[Any], tags: list[str], metadata: dict[str, Any]
    ):
        super().__init__(
            callbacks=callbacks,
            tags=tags,
            metadata=metadata,
            trace_id=span.trace_id,
        )
        self._span = span

    def complete(self, result: dict[str, Any]) -> None:
        self._span.update(output=redact_value(result_summary(result)))

    def fail(self, error: BaseException) -> None:
        self._span.update(
            level="ERROR",
            status_message=f"Workflow failed with {type(error).__name__}",
        )

    def score(
        self,
        name: str,
        value: ScoreValue,
        *,
        data_type: ScoreDataType | None = None,
        comment: str | None = None,
    ) -> None:
        self._span.score_trace(
            name=redact_text(name),
            value=redact_value(value),
            data_type=data_type,
            comment=redact_text(comment) if comment else None,
        )


class LangfuseObservability:
    def __init__(self, settings: ObservabilitySettings) -> None:
        if not settings.public_key or not settings.secret_key:
            raise RuntimeError("Langfuse requires LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY")
        self._settings = settings
        self._client = Langfuse(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            base_url=settings.base_url,
            environment=settings.environment,
            release=settings.release,
            sample_rate=settings.sample_rate,
            mask=lambda data: redact_value(data),
            mask_otel_spans=build_otel_masker(capture_content=settings.capture_content),
        )

    @contextmanager
    def trace_workflow(self, workflow: str, event: DomainEvent) -> Iterator[WorkflowTrace]:
        metadata = redact_value(workflow_metadata(workflow, event))
        tags = [redact_text(tag) for tag in workflow_tags(workflow, event)]
        trace_name = f"workflow.{workflow}"
        with propagate_attributes(
            session_id=event.correlation_id,
            metadata=metadata,
            tags=tags,
            trace_name=trace_name,
            environment=self._settings.environment,
        ):
            with self._client.start_as_current_observation(
                name=trace_name,
                as_type="agent",
                input=metadata,
                metadata=metadata,
            ) as span:
                yield LangfuseWorkflowTrace(
                    span=span,
                    callbacks=[CallbackHandler(public_key=self._settings.public_key)],
                    tags=tags,
                    metadata=metadata,
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
        self._client.create_score(
            trace_id=trace_id,
            name=redact_text(name),
            value=redact_value(value),
            data_type=data_type,
            comment=redact_text(comment) if comment else None,
        )

    def flush(self) -> None:
        self._client.flush()

    def shutdown(self) -> None:
        self._client.shutdown()
