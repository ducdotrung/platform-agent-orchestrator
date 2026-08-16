from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.core import DomainEvent


def event_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": "event-1",
        "type": "customer.extension.happened",
        "source": "test-suite",
        "occurred_at": datetime(2026, 8, 16, tzinfo=UTC),
        "correlation_id": "correlation-1",
        "idempotency_key": "test:event-1",
    }
    data.update(overrides)
    return data


def test_domain_event_accepts_plugin_defined_namespaced_type() -> None:
    event = DomainEvent.model_validate(event_data())

    assert event.type == "customer.extension.happened"
    assert event.data == {}
    assert event.metadata == {}


def test_domain_event_is_immutable() -> None:
    event = DomainEvent.model_validate(event_data())

    with pytest.raises(ValidationError):
        event.type = "changed.event"  # type: ignore[misc]


@pytest.mark.parametrize("field", ["id", "type", "source", "correlation_id", "idempotency_key"])
def test_domain_event_rejects_empty_identity_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        DomainEvent.model_validate(event_data(**{field: ""}))


def test_domain_event_serializes_transport_safe_values() -> None:
    event = DomainEvent.model_validate(
        event_data(data={"severity": "critical"}, tenant_id="tenant-a")
    )

    serialized = event.model_dump(mode="json")

    assert serialized["occurred_at"] == "2026-08-16T00:00:00Z"
    assert serialized["tenant_id"] == "tenant-a"
