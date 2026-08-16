"""Framework exceptions that do not depend on a runtime or provider."""

from __future__ import annotations

from collections.abc import Iterable


class OrchestratorError(Exception):
    """Base class for expected orchestrator failures."""


class DuplicateRegistrationError(OrchestratorError):
    """Raised when a registry name is registered more than once."""

    def __init__(self, kind: str, name: str) -> None:
        self.kind = kind
        self.name = name
        super().__init__(f"duplicate {kind} registration: {name}")


class UnknownFlowError(OrchestratorError):
    """Raised when a requested flow is not registered."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"unknown flow: {name}")


class UnknownAgentError(OrchestratorError):
    """Raised when a requested agent is not registered."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"unknown agent: {name}")


class MissingCapabilityError(OrchestratorError):
    """Raised when no provider supplies a requested capability."""

    def __init__(self, capability: str) -> None:
        self.capability = capability
        super().__init__(f"missing capability: {capability}")


class FlowCompatibilityError(OrchestratorError):
    """Raised when a flow's required capabilities are unavailable."""

    def __init__(self, *, flow: str, missing_capabilities: Iterable[str]) -> None:
        self.flow = flow
        self.missing_capabilities = tuple(sorted(missing_capabilities))
        missing = ", ".join(self.missing_capabilities)
        super().__init__(f"flow {flow!r} is missing required capabilities: {missing}")
