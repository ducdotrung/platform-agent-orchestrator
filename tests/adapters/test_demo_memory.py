from __future__ import annotations

import asyncio
from typing import Any

from platform_agent_orchestrator.adapters import DemoMemory, MemoryCapabilityProvider
from platform_agent_orchestrator.core import (
    CapabilityRequest,
    ExecutionContext,
    ExecutionIdentity,
    MemoryQuery,
    MemoryRecord,
)
from platform_agent_orchestrator.ports import MemoryPort


def execution_context(tenant_id: str | None) -> ExecutionContext:
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


def invoke(
    provider: MemoryCapabilityProvider,
    capability: str,
    arguments: dict[str, Any],
    context: ExecutionContext,
):
    return asyncio.run(
        provider.invoke(
            CapabilityRequest(
                capability=capability,
                operation=capability.rsplit(".", maxsplit=1)[-1],
                arguments=arguments,
            ),
            context=context,
        )
    )


def test_default_demo_learning_is_scoped_to_default_tenant() -> None:
    memory = DemoMemory()
    default_items = asyncio.run(
        memory.recall(
            MemoryQuery(query="payment timeout", scope="alert/order-service"),
            context=execution_context(None),
        )
    )
    tenant_items = asyncio.run(
        memory.recall(
            MemoryQuery(query="payment timeout", scope="alert/order-service"),
            context=execution_context("tenant-a"),
        )
    )

    assert len(default_items) == 1
    assert default_items[0].metadata["kind"] == "demo_execution_learning"
    assert tenant_items == []


def test_demo_memory_recall_record_feedback_and_idempotency() -> None:
    memory = DemoMemory()
    provider = MemoryCapabilityProvider(memory)
    context = execution_context("tenant-a")
    record = MemoryRecord(
        content="Restarting orders restored checkout after dependency saturation",
        idempotency_key="incident-42:outcome",
        scope="sre/orders/prod",
        metadata={"kind": "operational_outcome", "service": "orders"},
    )

    first = invoke(provider, "memory.record", record.model_dump(), context)
    duplicate = invoke(provider, "memory.record", record.model_dump(), context)
    memory_id = first.data["memory_id"]

    assert provider.capabilities == frozenset(
        {"memory.recall", "memory.record", "memory.feedback"}
    )
    assert isinstance(memory, MemoryPort)
    assert first.success is True
    assert duplicate.data["memory_id"] == memory_id

    recalled = invoke(
        provider,
        "memory.recall",
        MemoryQuery(
            query="orders restart saturation",
            scope="sre/orders/prod",
            filters={"kind": "operational_outcome"},
        ).model_dump(),
        context,
    )

    assert recalled.success is True
    assert [item["id"] for item in recalled.data["memories"]] == [memory_id]
    assert recalled.data["memories"][0]["score"] > 0

    feedback = invoke(
        provider,
        "memory.feedback",
        {"memory_id": memory_id, "useful": True, "reason": "Resolved incident"},
        context,
    )

    assert feedback.success is True
    assert memory.feedback_events == [
        {
            "memory_id": memory_id,
            "tenant_id": "tenant-a",
            "scope": "sre/orders/prod",
            "useful": True,
            "reason": "Resolved incident",
        }
    ]


def test_demo_memory_separates_tenants_and_scopes() -> None:
    memory = DemoMemory()
    tenant_a = execution_context("tenant-a")
    tenant_b = execution_context("tenant-b")
    record = MemoryRecord(
        content="Rollback restored the orders deployment",
        idempotency_key="deployment-7:outcome",
        scope="sre/orders/prod",
    )

    tenant_a_id = asyncio.run(memory.record(record, context=tenant_a))
    same_tenant = asyncio.run(
        memory.recall(
            MemoryQuery(query="orders rollback", scope="sre/orders/prod"),
            context=tenant_a,
        )
    )
    other_scope = asyncio.run(
        memory.recall(
            MemoryQuery(query="orders rollback", scope="sre/orders/staging"),
            context=tenant_a,
        )
    )
    other_tenant = asyncio.run(
        memory.recall(
            MemoryQuery(query="orders rollback", scope="sre/orders/prod"),
            context=tenant_b,
        )
    )
    tenant_b_id = asyncio.run(memory.record(record, context=tenant_b))

    assert [item.id for item in same_tenant] == [tenant_a_id]
    assert other_scope == []
    assert other_tenant == []
    assert tenant_b_id != tenant_a_id

    provider = MemoryCapabilityProvider(memory)
    cross_tenant_feedback = invoke(
        provider,
        "memory.feedback",
        {"memory_id": tenant_a_id, "useful": False, "reason": "Not applicable"},
        tenant_b,
    )
    assert cross_tenant_feedback.success is False
    assert "this tenant" in (cross_tenant_feedback.error or "")


def test_demo_memory_rejects_idempotency_conflict() -> None:
    memory = DemoMemory()
    provider = MemoryCapabilityProvider(memory)
    context = execution_context("tenant-a")
    original = MemoryRecord(
        content="Restart succeeded",
        idempotency_key="incident-1:outcome",
        scope="sre/orders/prod",
    )
    changed = original.model_copy(update={"content": "Rollback succeeded"})

    first = invoke(provider, "memory.record", original.model_dump(), context)
    conflict = invoke(provider, "memory.record", changed.model_dump(), context)

    assert first.success is True
    assert conflict.success is False
    assert "different record content" in (conflict.error or "")
