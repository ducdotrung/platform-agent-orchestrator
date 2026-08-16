from __future__ import annotations

import pytest

from platform_agent_orchestrator.core import DuplicateRegistrationError, UnknownAgentError
from platform_agent_orchestrator.registry import AgentRegistry

from .helpers import DummyAgent


def test_agent_registry_registers_lists_and_gets_agents() -> None:
    registry = AgentRegistry()
    agent = DummyAgent("engineering.developer")

    registry.register(agent.name, agent)

    assert registry.get(agent.name) is agent
    assert dict(registry.list()) == {agent.name: agent}


def test_agent_registry_rejects_duplicate_names() -> None:
    registry = AgentRegistry()
    registry.register("engineering.developer", DummyAgent("first"))

    with pytest.raises(DuplicateRegistrationError) as raised:
        registry.register("engineering.developer", DummyAgent("second"))

    assert (raised.value.kind, raised.value.name) == ("agent", "engineering.developer")


def test_agent_registry_rejects_unknown_names() -> None:
    with pytest.raises(UnknownAgentError):
        AgentRegistry().get("missing.agent")
