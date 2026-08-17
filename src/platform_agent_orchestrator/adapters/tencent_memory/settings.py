"""Credential-safe TencentDB Agent Memory adapter configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, model_validator

from .errors import TencentMemoryConfigurationError
from .models import TencentAuthentication


def _boolean(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _optional_secret(value: str | None) -> SecretStr | None:
    return SecretStr(value) if value and value.strip() else None


class TencentMemorySettings(BaseModel):
    """Process-owned settings that are never copied into workflow state."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    enabled: bool = False
    endpoint: AnyHttpUrl = "https://memory.tdai.tencentyun.com"
    api_key: SecretStr | None = Field(default=None, repr=False)
    service_id: str | None = Field(default=None, min_length=1, max_length=256)
    agent_id: str = Field(default="platform-agent-orchestrator", min_length=1, max_length=256)
    user_id: str = Field(default="platform-agent-orchestrator", min_length=1, max_length=256)
    default_team_id: str = Field(default="default", min_length=1, max_length=256)
    team_prefix: str = Field(default="platform", min_length=1, max_length=64)
    session_prefix: str = Field(default="platform-memory", min_length=1, max_length=64)
    timeout_seconds: float = Field(default=10.0, gt=0.0, le=120.0)
    verify_tls: bool = True
    max_remote_limit: int = Field(default=100, ge=1, le=100)
    idempotency_scan_limit: int = Field(default=10_000, ge=100, le=100_000)
    max_record_bytes: int = Field(default=8_192, ge=256, le=8_192)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        values = os.environ if environ is None else environ
        data: dict[str, Any] = {
            "enabled": _boolean(values.get("TENCENT_MEMORY_ENABLED"), default=False),
            "endpoint": values.get(
                "TENCENT_MEMORY_ENDPOINT", "https://memory.tdai.tencentyun.com"
            ),
            "api_key": _optional_secret(values.get("TENCENT_MEMORY_API_KEY")),
            "service_id": values.get("TENCENT_MEMORY_SERVICE_ID") or None,
            "agent_id": values.get(
                "TENCENT_MEMORY_AGENT_ID", "platform-agent-orchestrator"
            ),
            "user_id": values.get(
                "TENCENT_MEMORY_USER_ID", "platform-agent-orchestrator"
            ),
            "default_team_id": values.get("TENCENT_MEMORY_DEFAULT_TEAM_ID", "default"),
            "team_prefix": values.get("TENCENT_MEMORY_TEAM_PREFIX", "platform"),
            "session_prefix": values.get(
                "TENCENT_MEMORY_SESSION_PREFIX", "platform-memory"
            ),
            "timeout_seconds": values.get("TENCENT_MEMORY_TIMEOUT_SECONDS", "10"),
            "verify_tls": _boolean(
                values.get("TENCENT_MEMORY_VERIFY_TLS"), default=True
            ),
            "max_remote_limit": values.get("TENCENT_MEMORY_MAX_REMOTE_LIMIT", "100"),
            "idempotency_scan_limit": values.get(
                "TENCENT_MEMORY_IDEMPOTENCY_SCAN_LIMIT", "10000"
            ),
            "max_record_bytes": values.get("TENCENT_MEMORY_MAX_RECORD_BYTES", "8192"),
        }
        return cls.model_validate(data)

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        if self.endpoint.scheme != "https":
            raise ValueError("Tencent memory endpoint must use HTTPS")
        if self.enabled and (self.api_key is None or self.service_id is None):
            raise ValueError(
                "enabled Tencent memory requires TENCENT_MEMORY_API_KEY and "
                "TENCENT_MEMORY_SERVICE_ID"
            )
        return self

    def authentication(self) -> TencentAuthentication:
        if not self.enabled or self.api_key is None or self.service_id is None:
            raise TencentMemoryConfigurationError("Tencent memory is not configured")
        return TencentAuthentication(api_key=self.api_key, service_id=self.service_id)
