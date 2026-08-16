"""Plugin registration API independent of concrete registry implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .agent import Agent
from .capability import CapabilityProvider
from .flow import Flow


class FlowRegistrar(Protocol):
    """Minimal flow registry surface exposed to plugins."""

    def register(self, flow: Flow) -> None:
        """Register a flow."""

        ...


class AgentRegistrar(Protocol):
    """Minimal agent registry surface exposed to plugins."""

    def register(self, name: str, agent: Agent) -> None:
        """Register an agent under a unique name."""

        ...


class CapabilityRegistrar(Protocol):
    """Minimal capability registry surface exposed to plugins."""

    def register(self, provider: CapabilityProvider) -> None:
        """Register a capability provider."""

        ...


class PolicyRegistrar(Protocol):
    """Minimal policy registry surface exposed to plugins."""

    def register(self, name: str, policy: object) -> None:
        """Register a policy extension under a unique name."""

        ...


@dataclass(frozen=True)
class PluginContext:
    """Registration surfaces made available to a plugin."""

    flows: FlowRegistrar
    agents: AgentRegistrar
    capabilities: CapabilityRegistrar
    policies: PolicyRegistrar


class OrchestratorPlugin(Protocol):
    """Extension package that contributes flows, agents, capabilities, or policies."""

    @property
    def name(self) -> str:
        """Return the globally unique plugin name."""

        ...

    @property
    def version(self) -> str:
        """Return the plugin version."""

        ...

    def register(self, context: PluginContext) -> None:
        """Register this plugin's extensions."""

        ...
