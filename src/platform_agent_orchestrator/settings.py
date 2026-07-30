"""Validated process configuration with credential-free sample defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class DeploymentProfile(StrEnum):
    DEMO = "demo"
    LOCAL = "local"


class RuntimeRole(StrEnum):
    CLI = "cli"
    API = "api"
    WORKER = "worker"
    MIGRATION = "migration"


def _optional_secret(value: str | None) -> SecretStr | None:
    return SecretStr(value) if value and value.strip() else None


def _csv(value: str | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    if not items:
        raise ValueError("comma-separated allow-list cannot be empty")
    return items


def _boolean(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


class ApplicationSettings(BaseModel):
    """Settings held by the process boundary and never copied into graph state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: DeploymentProfile = DeploymentProfile.DEMO
    role: RuntimeRole = RuntimeRole.CLI
    adapter_mode: str = Field(default="demo", pattern=r"^demo$")
    bind_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    bind_port: int = Field(default=8080, ge=1, le=65_535)
    scope_id: str = Field(default="sock-shop-sample", min_length=1, max_length=128)
    allowed_sources: tuple[str, ...] = ("sample-sre-alert-agent",)
    allowed_services: tuple[str, ...] = (
        "carts",
        "catalogue",
        "front-end",
        "orders",
        "payment",
        "shipping",
        "user",
    )
    max_request_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    database_url: SecretStr | None = Field(default=None, repr=False)
    checkpoint_database_url: SecretStr | None = Field(default=None, repr=False)
    webhook_signing_secret: SecretStr | None = Field(default=None, repr=False)
    webhook_max_skew_seconds: int = Field(default=300, ge=30, le=900)
    webhook_nonce_ttl_seconds: int = Field(default=1_200, ge=120, le=3_600)
    external_egress_enabled: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        values = os.environ if environ is None else environ
        data: dict[str, Any] = {
            "profile": values.get("PLATFORM_PROFILE", "demo"),
            "role": values.get("PLATFORM_RUNTIME_ROLE", "cli"),
            "adapter_mode": values.get("PLATFORM_ADAPTER_MODE", "demo"),
            "bind_host": values.get("PLATFORM_BIND_HOST", "127.0.0.1"),
            "bind_port": values.get("PLATFORM_BIND_PORT", "8080"),
            "scope_id": values.get("PLATFORM_SCOPE_ID", "sock-shop-sample"),
            "allowed_sources": _csv(
                values.get("PLATFORM_ALLOWED_SOURCES"),
                default=("sample-sre-alert-agent",),
            ),
            "allowed_services": _csv(
                values.get("PLATFORM_ALLOWED_SERVICES"),
                default=(
                    "carts",
                    "catalogue",
                    "front-end",
                    "orders",
                    "payment",
                    "shipping",
                    "user",
                ),
            ),
            "max_request_bytes": values.get("PLATFORM_MAX_REQUEST_BYTES", "65536"),
            "database_url": _optional_secret(values.get("ORCHESTRATOR_DATABASE_URL")),
            "checkpoint_database_url": _optional_secret(
                values.get("CHECKPOINT_DATABASE_URL")
            ),
            "webhook_signing_secret": _optional_secret(
                values.get("PLATFORM_WEBHOOK_SIGNING_SECRET")
            ),
            "webhook_max_skew_seconds": values.get(
                "PLATFORM_WEBHOOK_MAX_SKEW_SECONDS", "300"
            ),
            "webhook_nonce_ttl_seconds": values.get(
                "PLATFORM_WEBHOOK_NONCE_TTL_SECONDS", "1200"
            ),
            "external_egress_enabled": _boolean(
                values.get("PLATFORM_EXTERNAL_EGRESS_ENABLED"), default=False
            ),
        }
        return cls.model_validate(data)

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if self.external_egress_enabled:
            raise ValueError("external egress is not enabled in the public sample")
        if self.webhook_nonce_ttl_seconds < self.webhook_max_skew_seconds * 2:
            raise ValueError("webhook nonce TTL must cover both sides of the clock-skew window")
        if (
            self.webhook_signing_secret is not None
            and len(self.webhook_signing_secret.get_secret_value()) < 32
        ):
            raise ValueError("webhook signing secret must contain at least 32 characters")
        if self.profile == DeploymentProfile.LOCAL:
            if self.role in {RuntimeRole.API, RuntimeRole.WORKER, RuntimeRole.MIGRATION}:
                if self.database_url is None:
                    raise ValueError("local service roles require ORCHESTRATOR_DATABASE_URL")
            if self.role == RuntimeRole.WORKER and self.checkpoint_database_url is None:
                raise ValueError("local worker requires CHECKPOINT_DATABASE_URL")
            for name, secret in (
                ("ORCHESTRATOR_DATABASE_URL", self.database_url),
                ("CHECKPOINT_DATABASE_URL", self.checkpoint_database_url),
            ):
                if secret is not None and not secret.get_secret_value().startswith(
                    ("postgresql://", "postgresql+psycopg://")
                ):
                    raise ValueError(f"{name} must use PostgreSQL")
        return self

    def public_summary(self) -> dict[str, Any]:
        """Return bounded readiness metadata with no credentials or allow-list details."""

        return {
            "profile": self.profile.value,
            "role": self.role.value,
            "adapter_mode": self.adapter_mode,
            "scope_id": self.scope_id,
            "external_egress_enabled": self.external_egress_enabled,
            "database_configured": self.database_url is not None,
            "checkpoint_database_configured": self.checkpoint_database_url is not None,
            "webhook_authentication_configured": self.webhook_signing_secret is not None,
        }
