from __future__ import annotations

from datetime import UTC, datetime

from platform_agent_orchestrator.core import DomainEvent, ExecutionContext, ExecutionIdentity


def event(event_type: str = "runtime.test.received") -> DomainEvent:
    return DomainEvent(
        id="event-1",
        type=event_type,
        source="runtime-tests",
        occurred_at=datetime(2026, 8, 16, tzinfo=UTC),
        correlation_id="correlation-1",
        idempotency_key=f"runtime:{event_type}:1",
        data={"route": "right"},
    )


def context(run_id: str = "run-1") -> ExecutionContext:
    return ExecutionContext(
        identity=ExecutionIdentity(
            run_id=run_id,
            thread_id=run_id,
            correlation_id="correlation-1",
            tenant_id="tenant-1",
        ),
        capabilities=object(),
        agents=object(),
        policy=object(),
        observability=object(),
        metadata={},
    )
