"""Startup compatibility validation for registered flows."""

from __future__ import annotations

from platform_agent_orchestrator.core.errors import FlowCompatibilityError
from platform_agent_orchestrator.sdk.flow import Flow

from .capability import CapabilityRegistry
from .flow import FlowRegistry


def validate_flow_capabilities(flow: Flow, capabilities: CapabilityRegistry) -> None:
    """Fail when a flow's required capabilities have no provider."""

    missing = flow.metadata.required_capabilities - capabilities.names()
    if missing:
        raise FlowCompatibilityError(
            flow=flow.metadata.name,
            missing_capabilities=missing,
        )


def validate_registry(*, flows: FlowRegistry, capabilities: CapabilityRegistry) -> None:
    """Validate every enabled flow before the application accepts traffic."""

    for flow in flows.list():
        validate_flow_capabilities(flow, capabilities)
