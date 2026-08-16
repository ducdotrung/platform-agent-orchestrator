from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.core import EvidenceRef, KnowledgeArtifact


def test_knowledge_artifact_preserves_revision_and_evidence_provenance() -> None:
    evidence = EvidenceRef(
        kind="code",
        locator="repo://orders/src/handler.py#L10",
        revision="abc123",
        label="order handler",
    )
    artifact = KnowledgeArtifact(
        id="artifact-1",
        kind="change-impact",
        revision="abc123",
        content={"affected_services": ["payments"]},
        evidence=[evidence],
        confidence=0.8,
    )

    assert artifact.evidence[0].revision == "abc123"
    assert artifact.model_dump(mode="json")["confidence"] == 0.8


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_knowledge_artifact_rejects_unbounded_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        KnowledgeArtifact(
            id="artifact-1",
            kind="search-result",
            revision="v1",
            content={},
            confidence=confidence,
        )
