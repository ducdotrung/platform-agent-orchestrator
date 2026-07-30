"""Dependency composition at the process boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from platform_agent_orchestrator.adapters import DemoPlatformServices, PlatformServices
from platform_agent_orchestrator.observability import (
    ObservabilityBackend,
    ObservabilitySettings,
    build_observability,
)
from platform_agent_orchestrator.registry import WorkflowRegistry
from platform_agent_orchestrator.settings import ApplicationSettings


@dataclass(frozen=True)
class RuntimeDependencies:
    settings: ApplicationSettings
    services: PlatformServices
    observability: ObservabilityBackend

    def registry(self, *, checkpointer: object | None = None) -> WorkflowRegistry:
        return WorkflowRegistry(
            self.services,
            checkpointer=checkpointer,
            observability=self.observability,
        )

    def shutdown(self) -> None:
        self.observability.shutdown()


def build_dependencies(
    settings: ApplicationSettings | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> RuntimeDependencies:
    if settings is not None and environ is not None:
        raise ValueError("pass settings or environ, not both")
    application_settings = settings or ApplicationSettings.from_env(environ)
    if application_settings.adapter_mode != "demo":
        raise ValueError(f"unsupported adapter mode: {application_settings.adapter_mode}")
    services = DemoPlatformServices().as_services()
    observability_settings = ObservabilitySettings.from_env(environ)
    observability = build_observability(observability_settings)
    return RuntimeDependencies(
        settings=application_settings,
        services=services,
        observability=observability,
    )
