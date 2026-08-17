from __future__ import annotations

from platform_agent_orchestrator.adapters.tencent_memory.settings import (
    TencentMemorySettings,
)
from platform_agent_orchestrator.core import ExecutionContext, ExecutionIdentity


def settings(**overrides: object) -> TencentMemorySettings:
    values: dict[str, object] = {
        "enabled": True,
        "api_key": "sk-test-secret-value",
        "service_id": "tdai-mem-test",
        "agent_id": "agent-platform",
        "user_id": "user-platform",
        "default_team_id": "default",
        "team_prefix": "team",
        "session_prefix": "memory",
    }
    values.update(overrides)
    return TencentMemorySettings.model_validate(values)


def context(tenant_id: str | None = "tenant-a") -> ExecutionContext:
    tenant = tenant_id or "default"
    return ExecutionContext(
        identity=ExecutionIdentity(
            run_id=f"run-{tenant}",
            thread_id=f"thread-{tenant}",
            correlation_id=f"correlation-{tenant}",
            tenant_id=tenant_id,
        ),
        capabilities=object(),
        agents=object(),
        policy=object(),
        observability=object(),
        metadata={},
    )
