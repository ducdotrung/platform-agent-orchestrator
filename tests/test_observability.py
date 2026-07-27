from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from platform_agent_orchestrator.adapters import DemoPlatformServices
from platform_agent_orchestrator.cli import sample_events
from platform_agent_orchestrator.contracts import DomainEvent
from platform_agent_orchestrator.observability import (
    NoOpObservability,
    ObservabilitySettings,
    WorkflowTrace,
    build_observability,
)
from platform_agent_orchestrator.observability.base import (
    ScoreDataType,
    ScoreValue,
    result_summary,
    workflow_metadata,
    workflow_tags,
)
from platform_agent_orchestrator.observability.masking import (
    REDACTED,
    is_content_attribute,
    redact_value,
)
from platform_agent_orchestrator.registry import WorkflowRegistry


@dataclass
class RecordingTrace(WorkflowTrace):
    completed: dict[str, Any] | None = None
    failed_with: type[BaseException] | None = None
    scores: list[tuple[str, ScoreValue, ScoreDataType | None]] = field(default_factory=list)

    def complete(self, result: dict[str, Any]) -> None:
        self.completed = result

    def fail(self, error: BaseException) -> None:
        self.failed_with = type(error)

    def score(
        self,
        name: str,
        value: ScoreValue,
        *,
        data_type: ScoreDataType | None = None,
        comment: str | None = None,
    ) -> None:
        self.scores.append((name, value, data_type))


class RecordingBackend:
    def __init__(self) -> None:
        self.trace: RecordingTrace | None = None
        self.delayed_scores: list[tuple[str, str, ScoreValue]] = []

    @contextmanager
    def trace_workflow(self, workflow: str, event: DomainEvent):
        self.trace = RecordingTrace(
            metadata=workflow_metadata(workflow, event),
            tags=workflow_tags(workflow, event),
            trace_id="trace-1",
        )
        yield self.trace

    def score(
        self,
        trace_id: str,
        name: str,
        value: ScoreValue,
        *,
        data_type: ScoreDataType | None = None,
        comment: str | None = None,
    ) -> None:
        self.delayed_scores.append((trace_id, name, value))

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


def test_settings_are_disabled_and_content_safe_by_default() -> None:
    settings = ObservabilitySettings.from_env({})

    assert settings.backend == "none"
    assert settings.capture_content is False
    assert isinstance(build_observability(settings), NoOpObservability)


def test_settings_validate_sampling_and_backend() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        ObservabilitySettings.from_env({"LANGFUSE_SAMPLE_RATE": "1.1"})
    with pytest.raises(ValueError, match="must be 'none' or 'langfuse'"):
        ObservabilitySettings.from_env({"PLATFORM_OBSERVABILITY": "other"})


def test_langfuse_requires_an_installed_sdk_and_credentials() -> None:
    with pytest.raises(RuntimeError):
        build_observability(ObservabilitySettings(backend="langfuse"))


def test_redaction_masks_structured_and_embedded_secrets() -> None:
    value = {
        "password": "do-not-export",
        "nested": {
            "authorization": "Bearer abc.def.ghi",
            "message": "Contact sre@example.com with token=super-secret-token",
        },
    }

    masked = redact_value(value)

    assert masked["password"] == REDACTED
    assert masked["nested"]["authorization"] == REDACTED
    assert "sre@example.com" not in masked["nested"]["message"]
    assert "super-secret-token" not in masked["nested"]["message"]
    assert redact_value("plain-secret", key="metadata.user.api-key") == REDACTED


def test_content_attribute_detection_is_specific() -> None:
    assert is_content_attribute("langfuse.observation.input")
    assert is_content_attribute("gen_ai.output.messages.0.content")
    assert is_content_attribute("tool.arguments")
    assert not is_content_attribute("gen_ai.usage.input_tokens")


def test_result_summary_excludes_state_bodies() -> None:
    summary = result_summary(
        {
            "status": "published",
            "event": {"payload": {"password": "secret"}},
            "evidence": [{"summary": "private"}],
            "artifacts": [{"content": "private"}],
            "snapshot_id": "snapshot-1",
        }
    )

    assert summary == {
        "status": "published",
        "interrupted": False,
        "evidence_count": 1,
        "artifact_count": 1,
        "snapshot_id": "snapshot-1",
    }


def test_registry_records_workflow_metadata_and_scores() -> None:
    backend = RecordingBackend()
    registry = WorkflowRegistry(
        DemoPlatformServices().as_services(),
        observability=backend,
    )

    result = registry.invoke("alert", sample_events()["alert"])

    assert backend.trace is not None
    assert backend.trace.completed == result
    assert backend.trace.metadata["workflow"] == "alert"
    assert backend.trace.metadata["event_type"] == "alert.received"
    assert "event" not in backend.trace.metadata
    assert "idempotency_key" not in backend.trace.metadata
    assert ("decision.confidence", 0.91, "NUMERIC") in backend.trace.scores

    registry.score_trace("trace-1", "human.correctness", True, data_type="BOOLEAN")
    assert backend.delayed_scores == [("trace-1", "human.correctness", True)]
