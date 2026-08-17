from __future__ import annotations

import pytest

from platform_agent_orchestrator.observability import (
    NoOpObservability,
    ObservabilitySettings,
    build_observability,
)
from platform_agent_orchestrator.observability.base import (
    result_summary,
)
from platform_agent_orchestrator.observability.masking import (
    REDACTED,
    is_content_attribute,
    redact_value,
)


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
