"""High-level LangChain agent factories.

The sample workflows depend on a ReasoningPort so tests can remain deterministic.
Production adapters can wrap these agents and convert their structured responses
into AgentDecision contracts.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from langchain.agents import create_agent

Role = Literal["developer", "qa", "product", "sre", "alert_reviewer"]

ROLE_PROMPTS: dict[Role, str] = {
    "developer": "Plan evidence-backed changes. Cite code, config, and dependency evidence.",
    "qa": "Design risk-based tests from changed behavior and transitive impact evidence.",
    "product": "Explain behavior, ownership, dependencies, and user impact without inventing facts.",  # noqa: E501
    "sre": "Propose bounded SRE actions. Never bypass approval or safety policy.",
    "alert_reviewer": "Assess alert impact, suppress noise conservatively, and cite service evidence.",  # noqa: E501
}


def create_role_agent(*, role: Role, model: str | Any, tools: Sequence[Any] = ()) -> Any:
    """Create a convenient LangChain agent; the returned agent is a LangGraph graph."""

    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=ROLE_PROMPTS[role],
    )
