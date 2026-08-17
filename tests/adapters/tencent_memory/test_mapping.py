from __future__ import annotations

import json

from platform_agent_orchestrator.adapters.tencent_memory.mapping import (
    map_record_request,
    map_search_request,
    map_search_response,
)
from platform_agent_orchestrator.adapters.tencent_memory.models import (
    TencentConversationItem,
    TencentSearchConversationResponse,
    TencentStoredMemoryEnvelope,
)
from platform_agent_orchestrator.core import MemoryQuery, MemoryRecord

from .helpers import context, settings


def stored_content(
    *,
    scope: str,
    content: str,
    kind: str,
    key: str,
    fingerprint: str = "a" * 64,
) -> str:
    envelope = TencentStoredMemoryEnvelope(
        schema="platform.memory.v1",
        content=content,
        scope=scope,
        metadata={"kind": kind},
        idempotency_key=key,
        fingerprint=fingerprint,
    )
    return envelope.model_dump_json(by_alias=True)


def test_record_mapping_maps_isolation_metadata_and_redacts_secrets() -> None:
    record = MemoryRecord(
        content="Use Bearer top-secret-token and api_key=sk-abcdefghijk",
        idempotency_key="incident-1:memory",
        scope="sre/orders/prod",
        metadata={
            "kind": "operational_outcome",
            "api_key": "sk-hidden-value",
            "nested": {"access_token": "hidden", "status": "resolved"},
        },
    )

    request, envelope = map_record_request(
        record,
        context=context("tenant-a"),
        settings=settings(),
    )
    serialized = request.model_dump_json()

    assert request.team_id == "team:tenant-a"
    assert request.agent_id == "agent-platform"
    assert request.user_id == "user-platform"
    assert request.session_id == "memory:sre/orders/prod"
    assert envelope.scope == record.scope
    assert envelope.metadata["kind"] == "operational_outcome"
    assert envelope.metadata["api_key"] == "[REDACTED]"
    assert envelope.metadata["nested"] == {
        "access_token": "[REDACTED]",
        "status": "resolved",
    }
    assert "top-secret-token" not in serialized
    assert "sk-abcdefghijk" not in serialized
    assert "sk-hidden-value" not in serialized


def test_search_mapping_maps_provider_and_metadata_filters() -> None:
    query = MemoryQuery(
        query="orders rollback",
        scope="sre/orders/prod",
        limit=2,
        filters={
            "kind": "operational_outcome",
            "time_start": "2026-08-01T00:00:00Z",
        },
    )

    request = map_search_request(query, context=context("tenant-a"), settings=settings())

    assert request.team_id == "team:tenant-a"
    assert request.session_id == "memory:sre/orders/prod"
    assert request.limit == 100
    assert request.time_start == "2026-08-01T00:00:00Z"
    assert request.time_end is None
    assert "kind" not in request.model_dump()


def test_search_response_enforces_scope_filters_and_framework_limit() -> None:
    matching = [
        TencentConversationItem(
            id=f"memory-{index}",
            role="assistant",
            content=stored_content(
                scope="sre/orders/prod",
                content=f"orders rollback outcome {index}",
                kind="operational_outcome",
                key=f"key-{index}",
            ),
            score=0.9 - index / 10,
        )
        for index in range(3)
    ]
    response = TencentSearchConversationResponse(
        messages=[
            *matching,
            TencentConversationItem(
                id="wrong-scope",
                role="assistant",
                content=stored_content(
                    scope="sre/orders/staging",
                    content="staging rollback",
                    kind="operational_outcome",
                    key="wrong-scope",
                ),
                score=0.99,
            ),
            TencentConversationItem(
                id="wrong-kind",
                role="assistant",
                content=stored_content(
                    scope="sre/orders/prod",
                    content="orders preference",
                    kind="preference",
                    key="wrong-kind",
                ),
                score=0.98,
            ),
        ]
    )
    query = MemoryQuery(
        query="orders rollback",
        scope="sre/orders/prod",
        limit=2,
        filters={"kind": "operational_outcome"},
    )

    memories = map_search_response(response, query)

    assert [item.id for item in memories] == ["memory-0", "memory-1"]
    assert all(item.metadata["kind"] == "operational_outcome" for item in memories)


def test_framework_metadata_is_encoded_only_inside_provider_message() -> None:
    record = MemoryRecord(
        content="Resolved checkout incident",
        idempotency_key="incident-2:memory",
        scope="alert/orders",
        metadata={"kind": "incident_learning", "tenant_note": "bounded"},
    )
    request, _envelope = map_record_request(
        record,
        context=context("tenant-a"),
        settings=settings(),
    )

    payload = json.loads(request.messages[0].content)

    assert payload["schema"] == "platform.memory.v1"
    assert payload["metadata"] == record.metadata
    assert "tencent" not in payload
