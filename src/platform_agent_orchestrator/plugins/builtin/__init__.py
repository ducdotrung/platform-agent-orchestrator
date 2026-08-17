"""Builtin flow plugin registration hook."""

from platform_agent_orchestrator.sdk.plugin import PluginContext


def register_builtin_plugins(context: PluginContext) -> None:
    """Register migrated builtin plugins; populated by Tasks 07 through 10."""

    del context


__all__ = ["register_builtin_plugins"]
