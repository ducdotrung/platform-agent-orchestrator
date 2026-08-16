"""Registries for flows, agents, and capability providers."""

from __future__ import annotations

from .agent import AgentRegistry
from .capability import CapabilityRegistry
from .flow import FlowRegistry
from .validation import validate_flow_capabilities, validate_registry

__all__ = [
    "AgentRegistry",
    "CapabilityRegistry",
    "FlowRegistry",
    "WorkflowRegistry",
    "validate_flow_capabilities",
    "validate_registry",
]


def __getattr__(name: str) -> object:
    """Load the legacy graph registry only for callers that still request it."""

    if name == "WorkflowRegistry":
        from .legacy import WorkflowRegistry

        return WorkflowRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
