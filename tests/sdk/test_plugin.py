from __future__ import annotations

from platform_agent_orchestrator.sdk import PluginContext


class RecordingRegistrar:
    def __init__(self) -> None:
        self.registrations: list[tuple[object, ...]] = []

    def register(self, *values: object) -> None:
        self.registrations.append(values)


class ExamplePlugin:
    name = "external.example"
    version = "1.0.0"

    def register(self, context: PluginContext) -> None:
        context.policies.register("example.policy", {"enabled": True})


def test_plugin_context_exposes_registration_surfaces_without_registry_dependency() -> None:
    registrar = RecordingRegistrar()
    context = PluginContext(
        flows=registrar,  # type: ignore[arg-type]
        agents=registrar,  # type: ignore[arg-type]
        capabilities=registrar,  # type: ignore[arg-type]
        policies=registrar,
    )

    ExamplePlugin().register(context)

    assert registrar.registrations == [("example.policy", {"enabled": True})]
