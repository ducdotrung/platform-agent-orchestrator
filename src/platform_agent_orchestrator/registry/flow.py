"""Flow registration and event resolution."""

from __future__ import annotations

from platform_agent_orchestrator.core.errors import (
    DuplicateRegistrationError,
    UnknownFlowError,
)
from platform_agent_orchestrator.core.events import DomainEvent
from platform_agent_orchestrator.sdk.flow import Flow


class FlowRegistry:
    """Store flows and resolve every flow that accepts an event."""

    def __init__(self) -> None:
        self._flows: dict[str, Flow] = {}

    def register(self, flow: Flow) -> None:
        """Register a flow and fail fast on duplicate metadata names."""

        name = flow.metadata.name
        if name in self._flows:
            raise DuplicateRegistrationError("flow", name)
        self._flows[name] = flow

    def get(self, name: str) -> Flow:
        """Return a registered flow or raise a framework lookup error."""

        try:
            return self._flows[name]
        except KeyError as exc:
            raise UnknownFlowError(name) from exc

    def list(self) -> tuple[Flow, ...]:
        """Return flows in deterministic registration order."""

        return tuple(self._flows.values())

    def resolve(self, event: DomainEvent) -> tuple[Flow, ...]:
        """Return zero, one, or multiple flows that accept an event."""

        return tuple(flow for flow in self._flows.values() if flow.accepts(event))
