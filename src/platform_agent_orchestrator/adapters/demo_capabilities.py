"""Runtime-neutral capability facades over deterministic demo adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from platform_agent_orchestrator.contracts import (
    DomainEvent as LegacyDomainEvent,
)
from platform_agent_orchestrator.contracts import (
    EventType,
    EvidenceKind,
)
from platform_agent_orchestrator.contracts import (
    EvidenceRef as LegacyEvidenceRef,
)
from platform_agent_orchestrator.contracts import (
    KnowledgeArtifact as LegacyKnowledgeArtifact,
)
from platform_agent_orchestrator.core.capabilities import CapabilityRequest, CapabilityResult
from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.models import (
    EvidenceRef,
    KnowledgeArtifact,
)
from platform_agent_orchestrator.ports.memory import MemoryItem

from .ports import ExtractionPort, KnowledgePort, PublicationPort


@dataclass(frozen=True)
class DemoCapabilityProvider:
    """Expose demo search and memory behind namespaced capabilities."""

    knowledge: KnowledgePort
    recorded_memories: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"knowledge.search", "memory.recall", "memory.record"})

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        del context
        if request.capability == "knowledge.search":
            query = str(request.arguments.get("query", "")).strip()
            limit = min(max(int(request.arguments.get("limit", 8)), 1), 20)
            evidence = [
                EvidenceRef(
                    kind=item.kind.value,
                    locator=item.locator,
                    revision=item.revision,
                    label=item.summary,
                    metadata={
                        "id": item.id,
                        "source": item.source,
                        "confidence": item.confidence,
                    },
                )
                for item in self.knowledge.search(query, limit=limit)
            ]
            return CapabilityResult(
                success=True,
                data={"evidence": [item.model_dump(mode="json") for item in evidence]},
                metadata={"provider": "demo"},
            )
        if request.capability == "memory.recall":
            query = str(request.arguments.get("query", "")).strip()
            role = str(request.arguments.get("role", "engineering"))
            memory = MemoryItem(
                id="demo-engineering-memory",
                content=(
                    "Previous checkout changes required explicit dependency-timeout "
                    "and degraded-mode regression coverage."
                ),
                score=0.9,
                metadata={"query": query[:128], "role": role[:32]},
            )
            return CapabilityResult(
                success=True,
                data={"memories": [memory.model_dump(mode="json")]},
                metadata={"provider": "demo"},
            )
        if request.capability == "memory.record":
            idempotency_key = str(request.arguments.get("idempotency_key", "")).strip()
            if not idempotency_key:
                return CapabilityResult(
                    success=False,
                    error="memory.record requires an idempotency_key",
                )
            receipt = (
                "demo-memory-"
                + hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]
            )
            self.recorded_memories.setdefault(
                idempotency_key,
                {
                    "receipt": receipt,
                    "subject": str(request.arguments.get("subject", ""))[:256],
                    "revision": str(request.arguments.get("revision", ""))[:128],
                    "snapshot_id": str(request.arguments.get("snapshot_id", ""))[:128],
                },
            )
            return CapabilityResult(
                success=True,
                data={"receipt": receipt},
                metadata={"provider": "demo"},
            )
        return CapabilityResult(
            success=False,
            error=f"unsupported demo capability: {request.capability}",
        )


@dataclass(frozen=True)
class DemoKnowledgeRefreshCapabilityProvider:
    """Translate v2 extraction/publication requests to deterministic demo ports."""

    extractor: ExtractionPort
    publisher: PublicationPort

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(
            {
                "knowledge.extract.code",
                "knowledge.extract.config",
                "knowledge.extract.docs",
                "knowledge.publish",
            }
        )

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        del context
        try:
            if request.capability.startswith("knowledge.extract."):
                return self._extract(request)
            if request.capability == "knowledge.publish":
                return self._publish(request)
        except (KeyError, TypeError, ValueError) as error:
            return CapabilityResult(success=False, error=str(error))
        return CapabilityResult(
            success=False,
            error=f"unsupported demo refresh capability: {request.capability}",
        )

    def _extract(self, request: CapabilityRequest) -> CapabilityResult:
        surface = request.capability.rsplit(".", maxsplit=1)[-1]
        adapter_surface = "document" if surface == "docs" else surface
        subject = str(request.arguments["subject"])
        source = str(request.arguments["source"])
        revision = str(request.arguments["revision"])
        changed_files = [str(path) for path in request.arguments["changed_files"]]
        event = LegacyDomainEvent.from_legacy(
            type=EventType.PR_MERGED,
            source=source,
            subject=subject,
            idempotency_key=f"demo-extract:{subject}:{revision}:{surface}",
            payload={"revision": revision, "changed_files": changed_files},
        )
        artifacts = self.extractor.extract(adapter_surface, event, changed_files)
        converted = [
            KnowledgeArtifact(
                id=artifact.id,
                kind="docs" if artifact.artifact_type == "document" else artifact.artifact_type,
                revision=artifact.revision,
                content=artifact.content,
                evidence=[
                    EvidenceRef(
                        kind=evidence.kind.value,
                        locator=evidence.locator,
                        revision=evidence.revision,
                        label=evidence.summary,
                        metadata={
                            "id": evidence.id,
                            "source": evidence.source,
                            "confidence": evidence.confidence,
                        },
                    )
                    for evidence in artifact.evidence
                ],
                confidence=artifact.confidence,
                metadata={"subject": artifact.subject},
            )
            for artifact in artifacts
        ]
        return CapabilityResult(
            success=True,
            data={"artifacts": [item.model_dump(mode="json") for item in converted]},
            metadata={"provider": "demo"},
        )

    def _publish(self, request: CapabilityRequest) -> CapabilityResult:
        subject = str(request.arguments["subject"])
        revision = str(request.arguments["revision"])
        idempotency_key = str(request.arguments["idempotency_key"])
        raw_artifacts = request.arguments["artifacts"]
        if not isinstance(raw_artifacts, list):
            raise TypeError("knowledge.publish artifacts must be a list")
        artifacts = [KnowledgeArtifact.model_validate(item) for item in raw_artifacts]
        legacy_artifacts = [
            LegacyKnowledgeArtifact(
                id=artifact.id,
                artifact_type="document" if artifact.kind == "docs" else artifact.kind,
                subject=subject,
                revision=artifact.revision,
                content=artifact.content,
                evidence=[
                    LegacyEvidenceRef(
                        id=str(evidence.metadata.get("id", evidence.locator)),
                        kind=EvidenceKind(evidence.kind),
                        source=str(evidence.metadata.get("source", "demo")),
                        locator=evidence.locator,
                        revision=evidence.revision,
                        summary=evidence.label or evidence.locator,
                        confidence=float(evidence.metadata.get("confidence", 1.0)),
                    )
                    for evidence in artifact.evidence
                ],
                confidence=artifact.confidence or 1.0,
            )
            for artifact in artifacts
        ]
        snapshot_id = self.publisher.publish(
            subject,
            revision,
            legacy_artifacts,
            idempotency_key=idempotency_key,
        )
        return CapabilityResult(
            success=True,
            data={"snapshot_id": snapshot_id},
            metadata={"provider": "demo", "atomic": True, "idempotent": True},
        )
