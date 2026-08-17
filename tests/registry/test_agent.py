from __future__ import annotations

import pytest

from platform_agent_orchestrator.core import DuplicateRegistrationError, UnknownAgentError
from platform_agent_orchestrator.registry import AgentRegistry

from .helpers import DummyAgent


def test_agent_registry_registers_lists_and_gets_agents() -> None:
    registry = AgentRegistry()
    agent = DummyAgent("engineering.developer")

    registry.register(agent)

    assert registry.get(agent.name) is agent
    assert dict(registry.list()) == {agent.name: agent}


def test_agent_registry_rejects_duplicate_names() -> None:
    registry = AgentRegistry()
    registry.register(DummyAgent("engineering.developer"))

    with pytest.raises(DuplicateRegistrationError) as raised:
        registry.register(DummyAgent("engineering.developer"))

    assert (raised.value.kind, raised.value.name) == ("agent", "engineering.developer")


def test_agent_registry_rejects_unknown_names() -> None:
    with pytest.raises(UnknownAgentError):
        AgentRegistry().get("missing.agent")


@pytest.mark.parametrize("name", ["", " padded"])
def test_agent_registry_rejects_invalid_canonical_name(name: str) -> None:
    with pytest.raises(ValueError, match="agent.name"):
        AgentRegistry().register(DummyAgent(name))
