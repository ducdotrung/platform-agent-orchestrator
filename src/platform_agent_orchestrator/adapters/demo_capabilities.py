"""Runtime-neutral capability facade over deterministic demo adapters."""

from __future__ import annotations

from dataclasses import dataclass

from platform_agent_orchestrator.core.capabilities import (
    CapabilityRequest,
    CapabilityResult,
)
from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.models import EvidenceRef
from platform_agent_orchestrator.ports.memory import MemoryItem

from .ports import KnowledgePort


@dataclass(frozen=True)
class DemoCapabilityProvider:
    """Expose demo knowledge and memory behind namespaced capabilities."""

    knowledge: KnowledgePort

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"knowledge.search", "memory.recall"})

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
                data={
                    "evidence": [item.model_dump(mode="json") for item in evidence]
                },
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
        return CapabilityResult(
            success=False,
            error=f"unsupported demo capability: {request.capability}",
        )
