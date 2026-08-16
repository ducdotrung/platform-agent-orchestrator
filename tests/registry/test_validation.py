from __future__ import annotations

import pytest

from platform_agent_orchestrator.core import FlowCompatibilityError
from platform_agent_orchestrator.registry import (
    CapabilityRegistry,
    FlowRegistry,
    validate_flow_capabilities,
    validate_registry,
)

from .helpers import DummyFlow, DummyProvider


def test_required_missing_capabilities_fail_startup_validation() -> None:
    flow = DummyFlow(
        "engineering-assistance",
        required_capabilities=frozenset({"knowledge.search", "memory.recall"}),
    )
    capabilities = CapabilityRegistry()
    capabilities.register(DummyProvider("knowledge.search"))

    with pytest.raises(FlowCompatibilityError) as raised:
        validate_flow_capabilities(flow, capabilities)

    assert raised.value.flow == "engineering-assistance"
    assert raised.value.missing_capabilities == ("memory.recall",)


def test_optional_missing_capabilities_do_not_fail_validation() -> None:
    flow = DummyFlow(
        "engineering-assistance",
        required_capabilities=frozenset({"knowledge.search"}),
        optional_capabilities=frozenset({"memory.recall"}),
    )
    capabilities = CapabilityRegistry()
    capabilities.register(DummyProvider("knowledge.search"))

    validate_flow_capabilities(flow, capabilities)


def test_registry_validation_checks_every_registered_flow() -> None:
    flows = FlowRegistry()
    flows.register(DummyFlow("ready"))
    flows.register(
        DummyFlow("not-ready", required_capabilities=frozenset({"notification.send"}))
    )

    with pytest.raises(FlowCompatibilityError) as raised:
        validate_registry(flows=flows, capabilities=CapabilityRegistry())

    assert raised.value.flow == "not-ready"
