"""Builtin flow plugin registration hook."""

from platform_agent_orchestrator.sdk.plugin import PluginContext

from .engineering import plugin as engineering_plugin


def register_builtin_plugins(context: PluginContext) -> None:
    """Register migrated builtin plugins; populated by Tasks 07 through 10."""

    engineering_plugin.register(context)


__all__ = ["register_builtin_plugins"]
