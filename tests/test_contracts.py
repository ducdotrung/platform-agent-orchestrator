from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.contracts import (
    AlertReceivedPayloadV1,
    EventEnvelopeV1,
    EvidenceKind,
    EvidenceRef,
)


def valid_alert_envelope() -> dict[str, object]:
    return {
        "schema_version": "1",
        "type": "monitoring.alert.received",
        "source": "sample-sre-alert-agent",
        "subject": "orders-high-errors",
        "idempotency_key": "sample:orders-high-errors:2026-07-30T10",
        "payload": {
            "alert_id": "orders-high-errors",
            "title": "Orders error rate is high",
            "service": "orders",
            "severity": "critical",
            "environment": "sample",
            "count": 42,
            "users": 7,
        },
    }


def test_alert_envelope_converts_to_internal_event() -> None:
    envelope = EventEnvelopeV1.model_validate(valid_alert_envelope())

    event = envelope.to_domain_event()

    assert event.type == "monitoring.alert.received"
    assert event.data["severity"] == "critical"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("unexpected",), True),
        (("schema_version",), "2"),
        (("type",), "scm.pull_request.merged"),
        (("payload", "unexpected"), True),
        (("payload", "severity"), "urgent"),
        (("payload", "title"), "x" * 4_097),
    ],
)
def test_alert_envelope_rejects_extra_unknown_oversized_and_incompatible_fields(
    path: tuple[str, ...], value: object
) -> None:
    candidate = valid_alert_envelope()
    target = candidate
    for key in path[:-1]:
        target = target[key]  # type: ignore[assignment,index]
    target[path[-1]] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        EventEnvelopeV1.model_validate(candidate)


def test_alert_payload_uses_strict_numeric_types() -> None:
    payload = valid_alert_envelope()["payload"]
    assert isinstance(payload, dict)
    payload["count"] = "42"

    with pytest.raises(ValidationError):
        AlertReceivedPayloadV1.model_validate(payload)


def test_evidence_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(
            kind=EvidenceKind.CODE,
            source="repo",
            locator="src/app.py:1",
            summary="Example",
            confidence=1.1,
        )
