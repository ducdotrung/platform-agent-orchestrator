from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.contracts import DomainEvent, EventType, EvidenceKind, EvidenceRef


def test_domain_event_requires_idempotency_identity() -> None:
    with pytest.raises(ValidationError):
        DomainEvent(
            type=EventType.ALERT_RECEIVED,
            source="sentry",
            subject="A-1",
            idempotency_key="",
        )


def test_evidence_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(
            kind=EvidenceKind.CODE,
            source="repo",
            locator="src/app.py:1",
            summary="Example",
            confidence=1.1,
        )
