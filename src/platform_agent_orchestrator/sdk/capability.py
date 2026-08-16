"""Generic capability provider interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from platform_agent_orchestrator.core.capabilities import CapabilityRequest, CapabilityResult
from platform_agent_orchestrator.core.context import ExecutionContext


@runtime_checkable
class CapabilityProvider(Protocol):
    """Provider that implements one or more namespaced capabilities."""

    @property
    def capabilities(self) -> frozenset[str]:
        """Return the capabilities implemented by this provider."""

        ...

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        """Invoke a capability using the runtime-owned execution context."""

        ...
