from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.adapters.tencent_memory import TencentMemorySettings


def test_tencent_memory_is_disabled_and_credential_free_by_default() -> None:
    settings = TencentMemorySettings.from_env({})

    assert settings.enabled is False
    assert settings.api_key is None
    assert settings.service_id is None
    assert str(settings.endpoint) == "https://memory.tdai.tencentyun.com/"


def test_enabled_tencent_memory_requires_credentials_and_https() -> None:
    with pytest.raises(ValidationError, match="requires TENCENT_MEMORY_API_KEY"):
        TencentMemorySettings.from_env({"TENCENT_MEMORY_ENABLED": "true"})

    with pytest.raises(ValidationError, match="must use HTTPS"):
        TencentMemorySettings.model_validate(
            {
                "enabled": True,
                "endpoint": "http://memory.example.test",
                "api_key": "sk-secret",
                "service_id": "memory-instance",
            }
        )


def test_authentication_secret_is_not_exposed_in_settings_repr() -> None:
    secret = "sk-never-print-this-value"
    settings = TencentMemorySettings.model_validate(
        {
            "enabled": True,
            "api_key": secret,
            "service_id": "tdai-mem-test",
        }
    )

    assert secret not in repr(settings)
    assert secret not in str(settings)
    assert settings.authentication().headers()["Authorization"] == f"Bearer {secret}"
    assert secret not in repr(settings.authentication())
