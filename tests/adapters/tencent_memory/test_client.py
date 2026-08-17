from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from platform_agent_orchestrator.adapters.tencent_memory import (
    HttpTencentMemoryClient,
    TencentMemoryInvalidResponseError,
    TencentMemoryNetworkError,
    TencentMemoryServiceError,
    TencentMemoryTimeoutError,
)
from platform_agent_orchestrator.adapters.tencent_memory.models import (
    TencentSearchConversationRequest,
)

from .helpers import settings


def search_request() -> TencentSearchConversationRequest:
    return TencentSearchConversationRequest(
        team_id="team:tenant-a",
        agent_id="agent-platform",
        user_id="user-platform",
        session_id="memory:sre/orders/prod",
        query="orders rollback",
        limit=2,
    )


def run_search(handler: httpx.MockTransport) -> object:
    async def execute() -> object:
        async with httpx.AsyncClient(transport=handler) as http_client:
            client = HttpTencentMemoryClient(settings(), http_client=http_client)
            return await client.search_conversation(search_request())

    return asyncio.run(execute())


def test_http_client_maps_auth_request_and_valid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert str(request.url) == (
            "https://memory.tdai.tencentyun.com/v3/conversation/search"
        )
        assert request.headers["authorization"] == "Bearer sk-test-secret-value"
        assert request.headers["x-tdai-service-id"] == "tdai-mem-test"
        assert payload["team_id"] == "team:tenant-a"
        assert payload["session_id"] == "memory:sre/orders/prod"
        assert payload["limit"] == 2
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "success",
                "request_id": "request-1",
                "data": {
                    "messages": [
                        {
                            "id": "memory-1",
                            "role": "assistant",
                            "content": "Rollback restored orders",
                            "score": 0.91,
                        }
                    ]
                },
            },
        )

    response = run_search(httpx.MockTransport(handler))

    assert response.messages[0].id == "memory-1"
    assert response.messages[0].score == 0.91


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, content=b"not JSON"), "non-JSON content"),
        (
            httpx.Response(
                200,
                json={"code": 0, "message": "ok", "data": {"unknown": []}},
            ),
            "malformed TencentSearchConversationResponse data",
        ),
        (
            httpx.Response(200, json={"code": 0, "data": {"messages": []}}),
            "malformed response envelope",
        ),
    ],
)
def test_http_client_rejects_malformed_responses(
    response: httpx.Response,
    expected: str,
) -> None:
    transport = httpx.MockTransport(lambda _request: response)

    with pytest.raises(TencentMemoryInvalidResponseError, match=expected):
        run_search(transport)


def test_http_client_reports_timeout_explicitly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("remote timeout", request=request)

    with pytest.raises(TencentMemoryTimeoutError, match="timed out"):
        run_search(httpx.MockTransport(handler))


def test_http_client_reports_network_error_explicitly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("remote unavailable", request=request)

    with pytest.raises(TencentMemoryNetworkError, match="network request failed"):
        run_search(httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="provider internal details"),
        httpx.Response(
            200,
            json={
                "code": 12001,
                "message": "provider internal details",
                "request_id": "request-2",
                "data": {},
            },
        ),
    ],
)
def test_http_client_reports_bounded_service_errors(response: httpx.Response) -> None:
    with pytest.raises(TencentMemoryServiceError) as raised:
        run_search(httpx.MockTransport(lambda _request: response))

    assert "provider internal details" not in str(raised.value)
    assert "sk-test-secret-value" not in str(raised.value)


def test_client_and_authentication_objects_are_not_serialized_in_memory_models() -> None:
    request = search_request()

    assert "api_key" not in request.model_dump()
    assert "service_id" not in request.model_dump()
    assert "client" not in request.model_dump()
