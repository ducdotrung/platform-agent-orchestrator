from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.core import EvidenceRef
from platform_agent_orchestrator.ports import MemoryItem
from platform_agent_orchestrator.sdk import AgentRequest, AgentResult


def test_agent_request_accepts_provider_neutral_evidence_and_memory() -> None:
    request = AgentRequest(
        task="Explain the affected service",
        input={"service": "orders"},
        evidence=[EvidenceRef(kind="code", locator="repo://orders/src/app.py", revision="abc")],
        memories=[MemoryItem(id="memory-1", content="A previous rollback fixed this")],
    )

    assert request.evidence[0].revision == "abc"
    assert request.memories[0].id == "memory-1"


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_agent_result_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        AgentResult(output={}, confidence=confidence)


def test_agent_request_rejects_provider_specific_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AgentRequest(task="answer", provider_messages=[])  # type: ignore[call-arg]
