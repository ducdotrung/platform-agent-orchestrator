from __future__ import annotations

import asyncio

import pytest

from platform_agent_orchestrator.core import (
    CapabilityRequest,
    DuplicateRegistrationError,
    MissingCapabilityError,
)
from platform_agent_orchestrator.registry import CapabilityRegistry

from .helpers import DummyProvider, execution_context


def test_capability_registry_registers_and_invokes_provider() -> None:
    registry = CapabilityRegistry()
    provider = DummyProvider("knowledge.search", "knowledge.change_impact")
    registry.register(provider)

    result = asyncio.run(
        registry.invoke(
            CapabilityRequest(capability="knowledge.search", arguments={"query": "orders"}),
            context=execution_context(),
        )
    )

    assert registry.names() == frozenset({"knowledge.search", "knowledge.change_impact"})
    assert result.data == {"capability": "knowledge.search"}
    assert provider.requests[0].arguments == {"query": "orders"}


def test_capability_registry_rejects_duplicates_atomically() -> None:
    registry = CapabilityRegistry()
    original = DummyProvider("knowledge.search")
    registry.register(original)

    with pytest.raises(DuplicateRegistrationError) as raised:
        registry.register(DummyProvider("knowledge.search", "memory.recall"))

    assert (raised.value.kind, raised.value.name) == ("capability", "knowledge.search")
    assert not registry.has("memory.recall")


def test_capability_registry_rejects_missing_capability_invocation() -> None:
    with pytest.raises(MissingCapabilityError) as raised:
        asyncio.run(
            CapabilityRegistry().invoke(
                CapabilityRequest(capability="missing.capability"),
                context=execution_context(),
            )
        )

    assert raised.value.capability == "missing.capability"
