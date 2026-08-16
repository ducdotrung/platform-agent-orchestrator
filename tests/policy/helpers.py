from __future__ import annotations

from platform_agent_orchestrator.core import (
    ActionIntent,
    ExecutionContext,
    ExecutionIdentity,
    RiskLevel,
)


def identity(*, run_id: str = "run-1") -> ExecutionIdentity:
    return ExecutionIdentity(
        run_id=run_id,
        thread_id="thread-1",
        correlation_id="correlation-1",
        tenant_id="tenant-1",
    )


def context() -> ExecutionContext:
    return ExecutionContext(
        identity=identity(),
        capabilities=object(),
        agents=object(),
        policy=object(),
        observability=object(),
        metadata={},
    )


def action(
    risk: RiskLevel | None,
    *,
    capability: str = "infra.execute",
    resource: str | None = "service/orders",
    arguments: dict[str, object] | None = None,
) -> ActionIntent:
    return ActionIntent(
        capability=capability,
        operation="restart",
        resource=resource,
        arguments=arguments or {"replicas": 2},
        requested_risk=risk,
        idempotency_key="action:orders:restart:1",
    )
