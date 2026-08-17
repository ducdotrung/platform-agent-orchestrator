"""Thin asynchronous HTTP client for TencentDB Agent Memory V3."""

from __future__ import annotations

from types import TracebackType
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .errors import (
    TencentMemoryInvalidResponseError,
    TencentMemoryNetworkError,
    TencentMemoryServiceError,
    TencentMemoryTimeoutError,
)
from .models import (
    TencentAddConversationRequest,
    TencentAddConversationResponse,
    TencentApiEnvelope,
    TencentQueryConversationRequest,
    TencentQueryConversationResponse,
    TencentSearchConversationRequest,
    TencentSearchConversationResponse,
)
from .settings import TencentMemorySettings

_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


class TencentMemoryClient(Protocol):
    """Provider client surface consumed by the framework adapter."""

    async def search_conversation(
        self, request: TencentSearchConversationRequest
    ) -> TencentSearchConversationResponse: ...

    async def query_conversation(
        self, request: TencentQueryConversationRequest
    ) -> TencentQueryConversationResponse: ...

    async def add_conversation(
        self, request: TencentAddConversationRequest
    ) -> TencentAddConversationResponse: ...


class HttpTencentMemoryClient:
    """Call documented Tencent V3 endpoints without leaking wire models outward."""

    def __init__(
        self,
        settings: TencentMemorySettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        authentication = settings.authentication()
        self._endpoint = str(settings.endpoint).rstrip("/")
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            headers=authentication.headers(),
            timeout=settings.timeout_seconds,
            verify=settings.verify_tls,
        )
        self._headers = authentication.headers() if http_client is not None else None

    async def __aenter__(self) -> HttpTencentMemoryClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search_conversation(
        self, request: TencentSearchConversationRequest
    ) -> TencentSearchConversationResponse:
        data = await self._post("/v3/conversation/search", request)
        return _validate_response(data, TencentSearchConversationResponse)

    async def query_conversation(
        self, request: TencentQueryConversationRequest
    ) -> TencentQueryConversationResponse:
        data = await self._post("/v3/conversation/query", request)
        return _validate_response(data, TencentQueryConversationResponse)

    async def add_conversation(
        self, request: TencentAddConversationRequest
    ) -> TencentAddConversationResponse:
        data = await self._post("/v3/conversation/add", request)
        return _validate_response(data, TencentAddConversationResponse)

    async def _post(self, path: str, request: BaseModel) -> dict[str, Any]:
        try:
            response = await self._client.post(
                f"{self._endpoint}{path}",
                headers=self._headers,
                json=request.model_dump(mode="json", exclude_none=True),
            )
        except httpx.TimeoutException as error:
            raise TencentMemoryTimeoutError("Tencent memory request timed out") from error
        except httpx.RequestError as error:
            raise TencentMemoryNetworkError("Tencent memory network request failed") from error

        request_id = response.headers.get("x-trace-id")
        if not 200 <= response.status_code < 300:
            raise TencentMemoryServiceError(
                status_code=response.status_code,
                request_id=request_id,
            )
        try:
            raw = response.json()
        except ValueError as error:
            raise TencentMemoryInvalidResponseError(
                "Tencent memory returned non-JSON content"
            ) from error
        try:
            envelope = TencentApiEnvelope.model_validate(raw)
        except ValidationError as error:
            raise TencentMemoryInvalidResponseError(
                "Tencent memory returned a malformed response envelope"
            ) from error
        if envelope.code != 0:
            raise TencentMemoryServiceError(
                status_code=response.status_code,
                code=envelope.code,
                request_id=envelope.request_id or request_id,
            )
        return envelope.data


def _validate_response(
    data: dict[str, Any],
    model: type[_ResponseModel],
) -> _ResponseModel:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise TencentMemoryInvalidResponseError(
            f"Tencent memory returned malformed {model.__name__} data"
        ) from error
