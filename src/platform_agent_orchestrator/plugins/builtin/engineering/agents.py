"""Provider-neutral deterministic Engineering role agents."""

from __future__ import annotations

from dataclasses import dataclass

from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.sdk.agent import AgentRequest, AgentResult


@dataclass(frozen=True)
class EngineeringAgent:
    """Produce bounded, evidence-citing guidance for one canonical role."""

    name: str
    role: str
    guidance: str

    async def invoke(
        self,
        request: AgentRequest,
        *,
        context: ExecutionContext,
    ) -> AgentResult:
        del context
        evidence_ids = [item.locator for item in request.evidence]
        memory_ids = [item.id for item in request.memories]
        summary = self.guidance
        if memory_ids:
            summary += " Relevant prior execution memory was considered."
        return AgentResult(
            output={
                "summary": summary,
                "role": self.role,
                "agent_name": self.name,
                "evidence_ids": evidence_ids,
                "memory_ids": memory_ids,
                "reasons": [
                    f"Answered from the {self.role} perspective",
                    f"Question: {request.task}",
                ],
            },
            confidence=0.9 if evidence_ids else 0.55,
            reasoning_summary="Applied deterministic role guidance to retrieved evidence.",
        )


def builtin_agents() -> tuple[EngineeringAgent, ...]:
    """Return the three agents with their canonical registry identities."""

    return (
        EngineeringAgent(
            name="engineering.developer",
            role="developer",
            guidance=(
                "Update the payment client and preserve the existing timeout boundary."
            ),
        ),
        EngineeringAgent(
            name="engineering.qa",
            role="qa",
            guidance=(
                "Cover checkout success, dependency timeout, retry, and degraded-mode paths."
            ),
        ),
        EngineeringAgent(
            name="engineering.ba",
            role="ba",
            guidance=(
                "The change can affect checkout completion and payment availability."
            ),
        ),
    )
