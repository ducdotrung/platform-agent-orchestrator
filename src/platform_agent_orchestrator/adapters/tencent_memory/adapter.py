"""Provider-neutral MemoryPort implementation backed by Tencent V3 conversations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.memory import MemoryItem, MemoryQuery, MemoryRecord

from .client import TencentMemoryClient
from .errors import (
    TencentMemoryConfigurationError,
    TencentMemoryIdempotencyConflictError,
    TencentMemoryIdempotencyUnavailableError,
    TencentMemoryInvalidResponseError,
)
from .mapping import (
    decode_stored_memory,
    map_feedback_request,
    map_record_request,
    map_search_request,
    map_search_response,
)
from .models import (
    TencentAddConversationRequest,
    TencentQueryConversationRequest,
    TencentStoredMemoryEnvelope,
)
from .settings import TencentMemorySettings


@dataclass(frozen=True)
class _RecordReceipt:
    fingerprint: str
    memory_id: str


@dataclass
class TencentMemoryAdapter:
    """Translate framework memory operations to isolated Tencent V3 requests."""

    client: TencentMemoryClient
    settings: TencentMemorySettings
    _idempotency: dict[tuple[str, str, str], _RecordReceipt] = field(
        default_factory=dict
    )
    _record_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        if not self.settings.enabled:
            raise TencentMemoryConfigurationError("Tencent memory adapter is disabled")

    async def recall(
        self,
        query: MemoryQuery,
        *,
        context: ExecutionContext,
    ) -> list[MemoryItem]:
        request = map_search_request(query, context=context, settings=self.settings)
        response = await self.client.search_conversation(request)
        return map_search_response(response, query)[: query.limit]

    async def record(
        self,
        record: MemoryRecord,
        *,
        context: ExecutionContext,
    ) -> str:
        request, envelope = map_record_request(
            record,
            context=context,
            settings=self.settings,
        )
        key = (request.team_id, request.session_id, record.idempotency_key)
        async with self._record_lock:
            local = self._idempotency.get(key)
            if local is not None:
                _validate_fingerprint(local.fingerprint, envelope.fingerprint)
                return local.memory_id

            remote = await self._find_remote_record(request, envelope)
            if remote is not None:
                self._idempotency[key] = remote
                return remote.memory_id

            response = await self.client.add_conversation(request)
            memory_id = _accepted_memory_id(response.accepted_ids, response.total_count)
            self._idempotency[key] = _RecordReceipt(
                fingerprint=envelope.fingerprint,
                memory_id=memory_id,
            )
            return memory_id

    async def feedback(
        self,
        memory_id: str,
        *,
        useful: bool,
        reason: str | None,
        context: ExecutionContext,
    ) -> None:
        if not memory_id.strip():
            raise TencentMemoryInvalidResponseError("memory feedback requires an id")
        request = map_feedback_request(
            memory_id,
            useful=useful,
            reason=reason,
            context=context,
            settings=self.settings,
        )
        response = await self.client.add_conversation(request)
        _accepted_memory_id(response.accepted_ids, response.total_count)

    async def _find_remote_record(
        self,
        request: TencentAddConversationRequest,
        expected: TencentStoredMemoryEnvelope,
    ) -> _RecordReceipt | None:
        offset = 0
        scanned = 0
        matches: list[_RecordReceipt] = []
        while True:
            remaining = self.settings.idempotency_scan_limit - scanned
            if remaining <= 0:
                raise TencentMemoryIdempotencyUnavailableError(
                    "Tencent idempotency scan limit reached; write refused"
                )
            page_limit = min(100, remaining)
            response = await self.client.query_conversation(
                TencentQueryConversationRequest(
                    team_id=request.team_id,
                    agent_id=request.agent_id,
                    user_id=request.user_id,
                    session_id=request.session_id,
                    limit=page_limit,
                    offset=offset,
                )
            )
            if len(response.messages) > page_limit:
                raise TencentMemoryInvalidResponseError(
                    "Tencent query exceeded the requested page limit"
                )
            for item in response.messages:
                stored = decode_stored_memory(item.content)
                if stored is None or stored.idempotency_key != expected.idempotency_key:
                    continue
                _validate_fingerprint(stored.fingerprint, expected.fingerprint)
                matches.append(
                    _RecordReceipt(
                        fingerprint=stored.fingerprint,
                        memory_id=item.id,
                    )
                )
            scanned += len(response.messages)
            offset += len(response.messages)
            if offset >= response.total:
                if not matches:
                    return None
                return min(matches, key=lambda receipt: receipt.memory_id)
            if not response.messages:
                raise TencentMemoryInvalidResponseError(
                    "Tencent query pagination stopped before reaching total"
                )


def _validate_fingerprint(actual: str, expected: str) -> None:
    if actual != expected:
        raise TencentMemoryIdempotencyConflictError(
            "memory idempotency key reused with different record content"
        )


def _accepted_memory_id(accepted_ids: list[str], total_count: int) -> str:
    if total_count != 1 or len(accepted_ids) != 1 or not accepted_ids[0].strip():
        raise TencentMemoryInvalidResponseError(
            "Tencent memory did not acknowledge exactly one message"
        )
    return accepted_ids[0]
