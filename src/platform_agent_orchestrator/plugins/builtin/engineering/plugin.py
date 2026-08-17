"""Engineering builtin plugin registration."""

from __future__ import annotations

from platform_agent_orchestrator.sdk.plugin import PluginContext

from .agents import builtin_agents
from .flow import EngineeringFlow


class EngineeringPlugin:
    name = "builtin.engineering"
    version = "2.0.0"

    def register(self, context: PluginContext) -> None:
        for agent in builtin_agents():
            context.agents.register(agent)
        context.flows.register(EngineeringFlow())


plugin = EngineeringPlugin()
