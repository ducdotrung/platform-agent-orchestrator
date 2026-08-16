from __future__ import annotations

import pytest

from platform_agent_orchestrator.core import DuplicateRegistrationError, UnknownFlowError
from platform_agent_orchestrator.registry import FlowRegistry

from .helpers import DummyFlow, domain_event


def test_flow_registry_resolves_zero_flows() -> None:
    registry = FlowRegistry()

    assert registry.resolve(domain_event()) == ()


def test_flow_registry_resolves_one_flow() -> None:
    registry = FlowRegistry()
    matching = DummyFlow("matching")
    registry.register(matching)
    registry.register(DummyFlow("other", event_types=frozenset({"other.event"})))

    assert registry.resolve(domain_event()) == (matching,)


def test_flow_registry_resolves_multiple_flows_in_registration_order() -> None:
    registry = FlowRegistry()
    first = DummyFlow("first")
    second = DummyFlow("second")
    registry.register(first)
    registry.register(second)

    assert registry.resolve(domain_event()) == (first, second)
    assert registry.list() == (first, second)


def test_flow_registry_rejects_duplicate_names() -> None:
    registry = FlowRegistry()
    registry.register(DummyFlow("duplicate"))

    with pytest.raises(DuplicateRegistrationError) as raised:
        registry.register(DummyFlow("duplicate"))

    assert (raised.value.kind, raised.value.name) == ("flow", "duplicate")


def test_flow_registry_rejects_unknown_names() -> None:
    with pytest.raises(UnknownFlowError):
        FlowRegistry().get("missing-flow")
