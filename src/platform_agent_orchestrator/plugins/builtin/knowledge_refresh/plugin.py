"""Knowledge Refresh builtin plugin registration."""

from __future__ import annotations

from platform_agent_orchestrator.sdk.plugin import PluginContext

from .flow import KnowledgeRefreshFlow


class KnowledgeRefreshPlugin:
    name = "builtin.knowledge-refresh"
    version = "2.0.0"

    def register(self, context: PluginContext) -> None:
        context.flows.register(KnowledgeRefreshFlow())


plugin = KnowledgeRefreshPlugin()
