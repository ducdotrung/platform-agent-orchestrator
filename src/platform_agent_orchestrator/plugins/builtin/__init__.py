"""Framework-owned builtin plugin registration hooks."""

from platform_agent_orchestrator.sdk.plugin import PluginContext

from .engineering import plugin as engineering_plugin
from .knowledge_refresh import plugin as knowledge_refresh_plugin


def register_builtin_plugins(context: PluginContext) -> None:
    """Register every migrated builtin plugin."""

    engineering_plugin.register(context)
    knowledge_refresh_plugin.register(context)


__all__ = ["register_builtin_plugins"]
