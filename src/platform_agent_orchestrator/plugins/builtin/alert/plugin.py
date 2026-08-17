"""Alert Analysis builtin plugin registration."""

from __future__ import annotations

from platform_agent_orchestrator.sdk.plugin import PluginContext

from .flow import AlertFlow


class AlertPlugin:
    name = "builtin.alert"
    version = "2.0.0"

    def register(self, context: PluginContext) -> None:
        context.flows.register(AlertFlow())


plugin = AlertPlugin()
