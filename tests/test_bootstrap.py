from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.bootstrap import build_dependencies
from platform_agent_orchestrator.cli import sample_events
from platform_agent_orchestrator.settings import (
    ApplicationSettings,
    DeploymentProfile,
    RuntimeRole,
)


def test_settings_use_credential_free_local_only_defaults() -> None:
    settings = ApplicationSettings.from_env({})

    assert settings.profile == DeploymentProfile.DEMO
    assert settings.role == RuntimeRole.CLI
    assert settings.bind_host == "127.0.0.1"
    assert settings.database_url is None
    assert settings.checkpoint_database_url is None
    assert settings.webhook_signing_secret is None
    assert settings.external_egress_enabled is False
    assert settings.max_request_bytes == 65_536


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"PLATFORM_BIND_PORT": "70000"}, "less than or equal"),
        ({"PLATFORM_MAX_REQUEST_BYTES": "10"}, "greater than or equal"),
        ({"PLATFORM_ALLOWED_SOURCES": " , "}, "allow-list cannot be empty"),
        ({"PLATFORM_EXTERNAL_EGRESS_ENABLED": "sometimes"}, "invalid boolean"),
        ({"PLATFORM_EXTERNAL_EGRESS_ENABLED": "true"}, "external egress"),
        ({"PLATFORM_ADAPTER_MODE": "company"}, "String should match pattern"),
        ({"PLATFORM_WEBHOOK_SIGNING_SECRET": "too-short"}, "at least 32"),
        (
            {
                "PLATFORM_WEBHOOK_MAX_SKEW_SECONDS": "300",
                "PLATFORM_WEBHOOK_NONCE_TTL_SECONDS": "500",
            },
            "nonce TTL",
        ),
    ],
)
def test_settings_reject_invalid_or_unsafe_configuration(
    environ: dict[str, str], message: str
) -> None:
    with pytest.raises((ValidationError, ValueError), match=message):
        ApplicationSettings.from_env(environ)


def test_local_service_roles_require_their_databases() -> None:
    with pytest.raises(ValidationError, match="ORCHESTRATOR_DATABASE_URL"):
        ApplicationSettings.from_env(
            {"PLATFORM_PROFILE": "local", "PLATFORM_RUNTIME_ROLE": "api"}
        )
    with pytest.raises(ValidationError, match="CHECKPOINT_DATABASE_URL"):
        ApplicationSettings.from_env(
            {
                "PLATFORM_PROFILE": "local",
                "PLATFORM_RUNTIME_ROLE": "worker",
                "ORCHESTRATOR_DATABASE_URL": "postgresql://sample:secret@db/app",
            }
        )


def test_database_settings_are_secret_and_public_summary_is_bounded() -> None:
    secret = "do-not-expose"
    settings = ApplicationSettings.from_env(
        {
            "PLATFORM_PROFILE": "local",
            "PLATFORM_RUNTIME_ROLE": "worker",
            "ORCHESTRATOR_DATABASE_URL": f"postgresql://sample:{secret}@db/app",
            "CHECKPOINT_DATABASE_URL": f"postgresql://sample:{secret}@db/checkpoint",
        }
    )

    assert secret not in repr(settings)
    assert secret not in str(settings.public_summary())
    assert settings.public_summary()["database_configured"] is True


def test_bootstrap_builds_demo_dependencies_without_secret_graph_state() -> None:
    secret = "not-graph-state"
    dependencies = build_dependencies(
        environ={
            "PLATFORM_PROFILE": "local",
            "PLATFORM_RUNTIME_ROLE": "worker",
            "ORCHESTRATOR_DATABASE_URL": f"postgresql://sample:{secret}@db/app",
            "CHECKPOINT_DATABASE_URL": f"postgresql://sample:{secret}@db/checkpoint",
        }
    )
    try:
        dispatched = asyncio.run(
            dependencies.dispatcher().dispatch(sample_events()["alert"])
        )
        assert len(dispatched) == 1
        result = dispatched[0].output
    finally:
        dependencies.shutdown()

    assert result["status"] == "notified"
    assert secret not in str(result)
    assert dependencies.settings.public_summary()["adapter_mode"] == "demo"
    assert dependencies.flows.get("alert").metadata.version == "2.0.0"
    assert dependencies.capabilities.names() == frozenset(
        {
            "alert.classify",
            "knowledge.search",
            "knowledge.change_impact",
            "notification.send",
            "knowledge.extract.code",
            "knowledge.extract.config",
            "knowledge.extract.docs",
            "knowledge.publish",
            "memory.recall",
            "memory.record",
            "memory.feedback",
            "infra.execute",
            "infra.verify",
        }
    )


def test_bootstrap_rejects_conflicting_configuration_sources() -> None:
    with pytest.raises(ValueError, match="not both"):
        build_dependencies(ApplicationSettings(), environ={})
