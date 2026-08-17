from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from platform_agent_orchestrator.adapters import MemoryCapabilityProvider
from platform_agent_orchestrator.adapters.tencent_memory import (
    TencentMemoryAdapter,
    TencentMemoryIdempotencyConflictError,
    TencentMemoryIdempotencyUnavailableError,
    TencentMemoryInvalidResponseError,
    TencentMemoryNetworkError,
)
from platform_agent_orchestrator.adapters.tencent_memory.mapping import (
    map_record_request,
)
from platform_agent_orchestrator.adapters.tencent_memory.models import (
    TencentAddConversationRequest,
    TencentAddConversationResponse,
    TencentConversationItem,
    TencentQueryConversationRequest,
    TencentQueryConversationResponse,
    TencentSearchConversationRequest,
    TencentSearchConversationResponse,
)
from platform_agent_orchestrator.core import CapabilityRequest, MemoryQuery, MemoryRecord
from platform_agent_orchestrator.ports import MemoryPort

from .helpers import context, settings


@dataclass
class FakeTencentClient:
    search_response: TencentSearchConversationResponse = field(
        default_factory=lambda: TencentSearchConversationResponse(messages=[])
    )
    query_responses: list[TencentQueryConversationResponse] = field(default_factory=list)
    add_responses: list[TencentAddConversationResponse] = field(default_factory=list)
    search_error: Exception | None = None
    query_error: Exception | None = None
    add_error: Exception | None = None
    search_requests: list[TencentSearchConversationRequest] = field(default_factory=list)
    query_requests: list[TencentQueryConversationRequest] = field(default_factory=list)
    add_requests: list[TencentAddConversationRequest] = field(default_factory=list)

    async def search_conversation(
        self, request: TencentSearchConversationRequest
    ) -> TencentSearchConversationResponse:
        self.search_requests.append(request)
        if self.search_error is not None:
            raise self.search_error
        return self.search_response

    async def query_conversation(
        self, request: TencentQueryConversationRequest
    ) -> TencentQueryConversationResponse:
        self.query_requests.append(request)
        if self.query_error is not None:
            raise self.query_error
        if self.query_responses:
            return self.query_responses.pop(0)
        return TencentQueryConversationResponse(messages=[], total=0)

    async def add_conversation(
        self, request: TencentAddConversationRequest
    ) -> TencentAddConversationResponse:
        self.add_requests.append(request)
        if self.add_error is not None:
            raise self.add_error
        if self.add_responses:
            return self.add_responses.pop(0)
        return TencentAddConversationResponse(
            accepted_ids=[f"memory-{len(self.add_requests)}"],
            accepted_versions=[1],
            total_count=1,
        )


def _stored_message(
    record: MemoryRecord,
    *,
    tenant_id: str = "tenant-a",
    memory_id: str = "remote-memory-1",
) -> TencentConversationItem:
    request, _envelope = map_record_request(
        record,
        context=context(tenant_id),
        settings=settings(),
    )
    return TencentConversationItem(
        id=memory_id,
        role="assistant",
        content=request.messages[0].content,
        version=1,
    )


def test_recall_maps_tenant_scope_and_enforces_framework_bound() -> None:
    record = MemoryRecord(
        content="Rollback restored orders",
        idempotency_key="incident-1",
        scope="sre/orders/prod",
    )
    messages = [
        _stored_message(record, memory_id=f"memory-{index}") for index in range(5)
    ]
    client = FakeTencentClient(
        search_response=TencentSearchConversationResponse(messages=messages)
    )
    adapter = TencentMemoryAdapter(client=client, settings=settings())

    recalled = asyncio.run(
        adapter.recall(
            MemoryQuery(query="orders rollback", scope="sre/orders/prod", limit=2),
            context=context("tenant-a"),
        )
    )
    asyncio.run(
        adapter.recall(
            MemoryQuery(query="orders rollback", scope="sre/orders/staging", limit=1),
            context=context("tenant-b"),
        )
    )

    assert [item.id for item in recalled] == ["memory-0", "memory-1"]
    assert client.search_requests[0].limit == 2
    assert client.search_requests[0].team_id == "team:tenant-a"
    assert client.search_requests[0].session_id == "memory:sre/orders/prod"
    assert client.search_requests[1].team_id == "team:tenant-b"
    assert client.search_requests[1].session_id == "memory:sre/orders/staging"
    assert isinstance(adapter, MemoryPort)


def test_record_is_idempotent_and_rejects_changed_content() -> None:
    client = FakeTencentClient()
    adapter = TencentMemoryAdapter(client=client, settings=settings())
    record = MemoryRecord(
        content="Restart restored checkout",
        idempotency_key="incident-42:outcome",
        scope="sre/orders/prod",
        metadata={"kind": "operational_outcome"},
    )

    async def exercise() -> tuple[str, str]:
        first = await adapter.record(record, context=context())
        duplicate = await adapter.record(record, context=context())
        return first, duplicate

    first, duplicate = asyncio.run(exercise())

    assert first == duplicate == "memory-1"
    assert len(client.query_requests) == 1
    assert len(client.add_requests) == 1

    changed = record.model_copy(update={"content": "Rollback restored checkout"})
    with pytest.raises(
        TencentMemoryIdempotencyConflictError,
        match="different record content",
    ):
        asyncio.run(adapter.record(changed, context=context()))
    assert len(client.add_requests) == 1


def test_restart_retry_finds_remote_idempotency_marker_without_writing() -> None:
    record = MemoryRecord(
        content="Scale-down completed after verification",
        idempotency_key="execution-7:outcome",
        scope="sre/payments/prod",
    )
    client = FakeTencentClient(
        query_responses=[
            TencentQueryConversationResponse(
                messages=[_stored_message(record, memory_id="persisted-memory")],
                total=1,
            )
        ]
    )
    adapter = TencentMemoryAdapter(client=client, settings=settings())

    memory_id = asyncio.run(adapter.record(record, context=context()))

    assert memory_id == "persisted-memory"
    assert len(client.query_requests) == 1
    assert client.add_requests == []


def test_record_fails_closed_when_remote_scan_cannot_prove_novelty() -> None:
    messages = [
        TencentConversationItem(
            id=f"conversation-{index}",
            role="assistant",
            content="unrelated provider conversation",
        )
        for index in range(100)
    ]
    client = FakeTencentClient(
        query_responses=[TencentQueryConversationResponse(messages=messages, total=101)]
    )
    adapter = TencentMemoryAdapter(
        client=client,
        settings=settings(idempotency_scan_limit=100),
    )
    record = MemoryRecord(
        content="Outcome known",
        idempotency_key="execution-8:outcome",
        scope="sre/payments/prod",
    )

    with pytest.raises(
        TencentMemoryIdempotencyUnavailableError,
        match="scan limit reached",
    ):
        asyncio.run(adapter.record(record, context=context()))
    assert client.add_requests == []


def test_feedback_is_mapped_to_an_isolated_versioned_message() -> None:
    client = FakeTencentClient()
    adapter = TencentMemoryAdapter(client=client, settings=settings())

    asyncio.run(
        adapter.feedback(
            "memory-12",
            useful=True,
            reason="Helped resolve the incident",
            context=context("tenant-a"),
        )
    )

    request = client.add_requests[0]
    payload = json.loads(request.messages[0].content)
    assert request.team_id == "team:tenant-a"
    assert request.session_id == "memory:feedback"
    assert payload == {
        "memory_id": "memory-12",
        "reason": "Helped resolve the incident",
        "schema": "platform.memory.feedback.v1",
        "useful": True,
    }


def test_malformed_framework_record_is_an_explicit_invalid_response() -> None:
    malformed = json.dumps(
        {
            "schema": "platform.memory.v1",
            "content": "missing required fields",
            "idempotency_key": "record-1",
        }
    )
    client = FakeTencentClient(
        search_response=TencentSearchConversationResponse(
            messages=[
                TencentConversationItem(
                    id="malformed",
                    role="assistant",
                    content=malformed,
                )
            ]
        )
    )
    adapter = TencentMemoryAdapter(client=client, settings=settings())

    with pytest.raises(
        TencentMemoryInvalidResponseError,
        match="malformed framework record",
    ):
        asyncio.run(
            adapter.recall(
                MemoryQuery(query="anything"),
                context=context(),
            )
        )


def test_network_and_record_failures_are_explicit_capability_failures() -> None:
    recall_client = FakeTencentClient(
        search_error=TencentMemoryNetworkError("Tencent network unavailable")
    )
    recall_adapter = TencentMemoryAdapter(client=recall_client, settings=settings())
    recall_provider = MemoryCapabilityProvider(recall_adapter)
    recall_result = asyncio.run(
        recall_provider.invoke(
            CapabilityRequest(
                capability="memory.recall",
                arguments=MemoryQuery(query="orders").model_dump(),
            ),
            context=context(),
        )
    )

    assert recall_result.success is False
    assert "network unavailable" in (recall_result.error or "")

    record_client = FakeTencentClient(
        add_error=TencentMemoryNetworkError("Tencent record failed")
    )
    record_adapter = TencentMemoryAdapter(client=record_client, settings=settings())
    record_provider = MemoryCapabilityProvider(record_adapter)
    record_result = asyncio.run(
        record_provider.invoke(
            CapabilityRequest(
                capability="memory.record",
                arguments=MemoryRecord(
                    content="Known outcome",
                    idempotency_key="execution-9:outcome",
                ).model_dump(),
            ),
            context=context(),
        )
    )

    assert record_result.success is False
    assert "record failed" in (record_result.error or "")
    assert len(record_client.add_requests) == 1


def test_invalid_add_acknowledgement_is_not_reported_as_a_success() -> None:
    client = FakeTencentClient(
        add_responses=[
            TencentAddConversationResponse(
                accepted_ids=[],
                total_count=0,
            )
        ]
    )
    adapter = TencentMemoryAdapter(client=client, settings=settings())

    with pytest.raises(
        TencentMemoryInvalidResponseError,
        match="did not acknowledge exactly one message",
    ):
        asyncio.run(
            adapter.record(
                MemoryRecord(content="Known outcome", idempotency_key="outcome-10"),
                context=context(),
            )
        )
