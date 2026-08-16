from __future__ import annotations

from platform_agent_orchestrator.core import CapabilityRequest, CapabilityResult
from platform_agent_orchestrator.sdk import CapabilityProvider


class FakeProvider:
    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"knowledge.search"})

    async def invoke(self, request: object, *, context: object) -> CapabilityResult:
        return CapabilityResult(success=True, data={"request": request, "context": context})


def test_capability_request_uses_generic_namespaced_contract() -> None:
    request = CapabilityRequest(capability="knowledge.search", arguments={"query": "orders"})

    assert request.operation == "invoke"
    assert request.arguments == {"query": "orders"}


def test_capability_provider_is_runtime_checkable() -> None:
    assert isinstance(FakeProvider(), CapabilityProvider)
