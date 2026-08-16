"""Agent implementation registry."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from platform_agent_orchestrator.core.errors import (
    DuplicateRegistrationError,
    UnknownAgentError,
)
from platform_agent_orchestrator.sdk.agent import Agent


class AgentRegistry:
    """Store provider-neutral agents by unique namespaced name."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, name: str, agent: Agent) -> None:
        """Register an agent and fail fast on duplicate names."""

        if name in self._agents:
            raise DuplicateRegistrationError("agent", name)
        self._agents[name] = agent

    def get(self, name: str) -> Agent:
        """Return a registered agent or raise a framework lookup error."""

        try:
            return self._agents[name]
        except KeyError as exc:
            raise UnknownAgentError(name) from exc

    def list(self) -> Mapping[str, Agent]:
        """Return a read-only snapshot of registered agents."""

        return MappingProxyType(dict(self._agents))
