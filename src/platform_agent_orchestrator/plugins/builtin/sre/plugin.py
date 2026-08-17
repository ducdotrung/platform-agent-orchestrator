"""SRE execution builtin plugin registration."""

from __future__ import annotations

from platform_agent_orchestrator.sdk.plugin import PluginContext

from .flow import SREFlow


class SREPlugin:
    name = "builtin.sre"
    version = "2.0.0"

    def register(self, context: PluginContext) -> None:
        context.flows.register(SREFlow())


plugin = SREPlugin()
