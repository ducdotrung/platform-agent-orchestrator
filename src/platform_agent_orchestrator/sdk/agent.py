"""Provider-neutral agent API."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.memory import MemoryItem
from platform_agent_orchestrator.core.models import EvidenceRef


class AgentRequest(BaseModel):
    """Structured input accepted by any registered agent implementation."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    memories: list[MemoryItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Provider-neutral agent response without hidden reasoning state."""

    model_config = ConfigDict(extra="forbid")

    output: dict[str, Any]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reasoning_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Agent(Protocol):
    """Structural interface implemented by deterministic or model-backed agents."""

    @property
    def name(self) -> str:
        """Return the unique registry name for this agent."""

        ...

    async def invoke(
        self,
        request: AgentRequest,
        *,
        context: ExecutionContext,
    ) -> AgentResult:
        """Execute a structured agent task."""

        ...
