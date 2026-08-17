"""Deterministic, tenant-isolated memory provider for demos and tests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.memory import MemoryItem, MemoryQuery, MemoryRecord


def _seed_items() -> dict[tuple[str | None, str | None, str], MemoryItem]:
    content = (
        "Previous checkout payment dependency-timeout changes required explicit "
        "degraded-mode and regression coverage."
    )
    scopes = (
        "engineering/developer",
        "engineering/qa",
        "engineering/ba",
        "alert/order-service",
        "sre/payment-service/prod",
    )
    return {
        (None, scope, f"demo-memory-{scope.replace('/', '-')}"): MemoryItem(
            id=f"demo-memory-{scope.replace('/', '-')}",
            content=content,
            metadata={"kind": "demo_execution_learning"},
        )
        for scope in scopes
    }


@dataclass
class DemoMemory:
    """Store bounded memories in process with deterministic record identifiers."""

    _items: dict[tuple[str | None, str | None, str], MemoryItem] = field(
        default_factory=_seed_items
    )
    _idempotency: dict[tuple[str | None, str], tuple[str, str]] = field(
        default_factory=dict
    )
    feedback_events: list[dict[str, Any]] = field(default_factory=list)

    async def recall(
        self,
        query: MemoryQuery,
        *,
        context: ExecutionContext,
    ) -> list[MemoryItem]:
        tenant_id = context.identity.tenant_id
        ranked: list[MemoryItem] = []
        for (item_tenant, item_scope, _memory_id), item in self._items.items():
            if item_tenant != tenant_id or item_scope != query.scope:
                continue
            if any(item.metadata.get(key) != value for key, value in query.filters.items()):
                continue
            score = _relevance(query.query, item.content)
            if score == 0:
                continue
            ranked.append(item.model_copy(update={"score": score}))
        ranked.sort(key=lambda item: (-(item.score or 0.0), item.id))
        return ranked[: query.limit]

    async def record(
        self,
        record: MemoryRecord,
        *,
        context: ExecutionContext,
    ) -> str:
        tenant_id = context.identity.tenant_id
        fingerprint = _fingerprint(record)
        idempotency_key = (tenant_id, record.idempotency_key)
        previous = self._idempotency.get(idempotency_key)
        if previous is not None:
            previous_fingerprint, memory_id = previous
            if previous_fingerprint != fingerprint:
                raise ValueError(
                    "memory idempotency key reused with different record content"
                )
            return memory_id

        memory_id = _memory_id(tenant_id, record.idempotency_key)
        item_key = (tenant_id, record.scope, memory_id)
        self._items[item_key] = MemoryItem(
            id=memory_id,
            content=record.content,
            metadata=dict(record.metadata),
        )
        self._idempotency[idempotency_key] = (fingerprint, memory_id)
        return memory_id

    async def feedback(
        self,
        memory_id: str,
        *,
        useful: bool,
        reason: str | None,
        context: ExecutionContext,
    ) -> None:
        tenant_id = context.identity.tenant_id
        matches = [
            key
            for key in self._items
            if key[0] == tenant_id and key[2] == memory_id
        ]
        if not matches:
            raise ValueError("memory feedback target was not found for this tenant")
        self.feedback_events.append(
            {
                "memory_id": memory_id,
                "tenant_id": tenant_id,
                "scope": matches[0][1],
                "useful": useful,
                "reason": reason,
            }
        )


def _fingerprint(record: MemoryRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"idempotency_key"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _memory_id(tenant_id: str | None, idempotency_key: str) -> str:
    tenant = tenant_id or "<default>"
    digest = hashlib.sha256(f"{tenant}|{idempotency_key}".encode()).hexdigest()[:20]
    return f"demo-memory-{digest}"


def _relevance(query: str, content: str) -> float:
    query_tokens = set(re.findall(r"[a-z0-9_]+", query.lower()))
    content_tokens = set(re.findall(r"[a-z0-9_]+", content.lower()))
    if not query_tokens:
        return 0.0
    return round(len(query_tokens.intersection(content_tokens)) / len(query_tokens), 6)
