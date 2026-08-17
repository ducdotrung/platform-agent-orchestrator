"""Dependency composition at the process boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from platform_agent_orchestrator.adapters import DemoPlatformServices, PlatformServices
from platform_agent_orchestrator.adapters.demo_capabilities import (
    DemoCapabilityProvider,
    DemoKnowledgeRefreshCapabilityProvider,
)
from platform_agent_orchestrator.observability import (
    ObservabilityBackend,
    ObservabilitySettings,
    build_observability,
)
from platform_agent_orchestrator.plugins.builtin import register_builtin_plugins
from platform_agent_orchestrator.policy import DefaultPolicyEngine
from platform_agent_orchestrator.registry import (
    AgentRegistry,
    CapabilityRegistry,
    FlowRegistry,
    WorkflowRegistry,
    validate_registry,
)
from platform_agent_orchestrator.runtime.context import ExecutionContextFactory
from platform_agent_orchestrator.runtime.dispatcher import Dispatcher
from platform_agent_orchestrator.runtime.langgraph import LangGraphWorkflowRuntime
from platform_agent_orchestrator.runtime.legacy_adapter import (
    LegacyWorkflowRuntime,
    TransitionalWorkflowRuntime,
    register_legacy_alert,
)
from platform_agent_orchestrator.sdk.plugin import PluginContext
from platform_agent_orchestrator.settings import ApplicationSettings


@dataclass
class _PolicyExtensions:
    values: dict[str, object] = field(default_factory=dict)

    def register(self, name: str, policy: object) -> None:
        if name in self.values:
            raise ValueError(f"duplicate policy registration: {name}")
        self.values[name] = policy


def _default_flows() -> FlowRegistry:
    flows = FlowRegistry()
    register_legacy_alert(flows)
    return flows


@dataclass(frozen=True)
class RuntimeDependencies:
    settings: ApplicationSettings
    services: PlatformServices
    observability: ObservabilityBackend
    flows: FlowRegistry = field(default_factory=_default_flows)
    agents: AgentRegistry = field(default_factory=AgentRegistry)
    capabilities: CapabilityRegistry = field(default_factory=CapabilityRegistry)
    policy: DefaultPolicyEngine = field(default_factory=DefaultPolicyEngine)

    def registry(
        self,
        *,
        checkpointer: object | None = None,
        services: PlatformServices | None = None,
    ) -> WorkflowRegistry:
        """Build the legacy registry until its workflows finish migrating."""

        return WorkflowRegistry(
            services or self.services,
            checkpointer=checkpointer,
            observability=self.observability,
        )

    def context_factory(self) -> ExecutionContextFactory:
        return ExecutionContextFactory(
            capabilities=self.capabilities,
            agents=self.agents,
            policy=self.policy,
            observability=self.observability,
        )

    def dispatcher(
        self,
        *,
        checkpointer: object | None = None,
        services: PlatformServices | None = None,
    ) -> Dispatcher:
        """Compose registry routing with a runtime hidden behind WorkflowRuntime."""

        runtime = TransitionalWorkflowRuntime(
            primary=LangGraphWorkflowRuntime(checkpointer=checkpointer),
            legacy=LegacyWorkflowRuntime(
                self.registry(checkpointer=checkpointer, services=services)
            ),
        )
        return Dispatcher(
            flows=self.flows,
            runtime=runtime,
            contexts=self.context_factory(),
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
    demo = DemoPlatformServices()
    services = demo.as_services()
    observability_settings = ObservabilitySettings.from_env(environ)
    observability = build_observability(observability_settings)
    flows = FlowRegistry()
    agents = AgentRegistry()
    capabilities = CapabilityRegistry()
    capabilities.register(DemoCapabilityProvider(demo.knowledge))
    capabilities.register(
        DemoKnowledgeRefreshCapabilityProvider(demo.extractor, demo.publisher)
    )
    policies = _PolicyExtensions()
    register_builtin_plugins(
        PluginContext(
            flows=flows,
            agents=agents,
            capabilities=capabilities,
            policies=policies,
        )
    )
    register_legacy_alert(flows)
    validate_registry(flows=flows, capabilities=capabilities)
    return RuntimeDependencies(
        settings=application_settings,
        services=services,
        observability=observability,
        flows=flows,
        agents=agents,
        capabilities=capabilities,
        policy=DefaultPolicyEngine(),
    )
