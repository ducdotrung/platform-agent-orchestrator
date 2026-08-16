"""Capability provider registry and invocation routing."""

from __future__ import annotations

from platform_agent_orchestrator.core.capabilities import CapabilityRequest, CapabilityResult
from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.errors import (
    DuplicateRegistrationError,
    MissingCapabilityError,
)
from platform_agent_orchestrator.sdk.capability import CapabilityProvider


class CapabilityRegistry:
    """Route each namespaced capability to one configured provider."""

    def __init__(self) -> None:
        self._providers: dict[str, CapabilityProvider] = {}

    def register(self, provider: CapabilityProvider) -> None:
        """Atomically register every capability exposed by a provider."""

        duplicates = provider.capabilities.intersection(self._providers)
        if duplicates:
            raise DuplicateRegistrationError("capability", sorted(duplicates)[0])

        for capability in sorted(provider.capabilities):
            self._providers[capability] = provider

    def has(self, capability: str) -> bool:
        """Return whether a provider is registered for a capability."""

        return capability in self._providers

    def names(self) -> frozenset[str]:
        """Return all available capability names."""

        return frozenset(self._providers)

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        """Route a request to its provider or raise a framework lookup error."""

        provider = self._providers.get(request.capability)
        if provider is None:
            raise MissingCapabilityError(request.capability)
        return await provider.invoke(request, context=context)
