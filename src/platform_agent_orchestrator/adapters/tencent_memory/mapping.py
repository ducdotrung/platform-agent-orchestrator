"""Mapping between framework memory contracts and Tencent V3 conversations."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import ValidationError

from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.memory import MemoryItem, MemoryQuery, MemoryRecord

from .errors import TencentMemoryInvalidResponseError
from .models import (
    TencentAddConversationRequest,
    TencentConversationMessage,
    TencentFeedbackEnvelope,
    TencentIsolation,
    TencentSearchConversationRequest,
    TencentSearchConversationResponse,
    TencentStoredMemoryEnvelope,
)
from .settings import TencentMemorySettings

_PROVIDER_FILTERS = frozenset({"time_start", "time_end"})
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|credential|password|secret|token|api[_-]?key)", re.IGNORECASE
)
_SENSITIVE_TEXT = (
    re.compile(r"(?i)\bBearer\s+\S+"),
    re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"),
    re.compile(
        r"(?i)\b(password|token|secret|api[_-]?key)\s*[:=]\s*\S+"
    ),
)


def map_isolation(
    settings: TencentMemorySettings,
    context: ExecutionContext,
    scope: str | None,
    *,
    feedback: bool = False,
) -> TencentIsolation:
    """Map framework tenant/scope identifiers into Tencent ownership dimensions."""

    tenant = context.identity.tenant_id or settings.default_team_id
    session_scope = "feedback" if feedback else (scope or "default")
    return TencentIsolation(
        team_id=_identifier(settings.team_prefix, tenant),
        agent_id=settings.agent_id,
        user_id=settings.user_id,
        session_id=_identifier(settings.session_prefix, session_scope),
    )


def map_search_request(
    query: MemoryQuery,
    *,
    context: ExecutionContext,
    settings: TencentMemorySettings,
) -> TencentSearchConversationRequest:
    isolation = map_isolation(settings, context, query.scope)
    client_filters = _client_filters(query.filters)
    remote_limit = (
        settings.max_remote_limit
        if _metadata_filters(query.filters)
        else min(query.limit, settings.max_remote_limit)
    )
    return TencentSearchConversationRequest(
        **isolation.model_dump(),
        query=_redact_text(query.query),
        limit=remote_limit,
        **client_filters,
    )


def map_record_request(
    record: MemoryRecord,
    *,
    context: ExecutionContext,
    settings: TencentMemorySettings,
) -> tuple[TencentAddConversationRequest, TencentStoredMemoryEnvelope]:
    isolation = map_isolation(settings, context, record.scope)
    envelope = TencentStoredMemoryEnvelope(
        schema="platform.memory.v1",
        content=_redact_text(record.content),
        scope=record.scope,
        metadata=_redact_mapping(record.metadata),
        idempotency_key=record.idempotency_key,
        fingerprint=memory_fingerprint(record),
    )
    encoded = _encode(envelope.model_dump(mode="json", by_alias=True))
    if len(encoded.encode("utf-8")) > settings.max_record_bytes:
        raise TencentMemoryInvalidResponseError(
            "framework memory exceeds the configured Tencent record size"
        )
    return (
        TencentAddConversationRequest(
            **isolation.model_dump(),
            messages=[TencentConversationMessage(role="assistant", content=encoded)],
        ),
        envelope,
    )


def map_feedback_request(
    memory_id: str,
    *,
    useful: bool,
    reason: str | None,
    context: ExecutionContext,
    settings: TencentMemorySettings,
) -> TencentAddConversationRequest:
    isolation = map_isolation(settings, context, None, feedback=True)
    envelope = TencentFeedbackEnvelope(
        schema="platform.memory.feedback.v1",
        memory_id=memory_id,
        useful=useful,
        reason=_redact_text(reason) if reason is not None else None,
    )
    encoded = _encode(envelope.model_dump(mode="json", by_alias=True))
    if len(encoded.encode("utf-8")) > settings.max_record_bytes:
        raise TencentMemoryInvalidResponseError(
            "framework feedback exceeds the configured Tencent record size"
        )
    return TencentAddConversationRequest(
        **isolation.model_dump(),
        messages=[TencentConversationMessage(role="assistant", content=encoded)],
    )


def map_search_response(
    response: TencentSearchConversationResponse,
    query: MemoryQuery,
) -> list[MemoryItem]:
    """Validate, filter, redact, and enforce the framework result bound."""

    metadata_filters = _metadata_filters(query.filters)
    memories: list[MemoryItem] = []
    for item in response.messages:
        envelope = decode_stored_memory(item.content)
        if envelope is not None:
            if envelope.scope != query.scope:
                continue
            content = envelope.content
            metadata = _redact_mapping(envelope.metadata)
        else:
            content = _redact_text(item.content)
            metadata = {"kind": "conversation"}
        if any(metadata.get(key) != value for key, value in metadata_filters.items()):
            continue
        memories.append(
            MemoryItem(
                id=item.id,
                content=content,
                score=item.score,
                metadata=metadata,
            )
        )
        if len(memories) == query.limit:
            break
    return memories


def decode_stored_memory(content: str) -> TencentStoredMemoryEnvelope | None:
    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or raw.get("schema") != "platform.memory.v1":
        return None
    try:
        return TencentStoredMemoryEnvelope.model_validate(raw)
    except ValidationError as error:
        raise TencentMemoryInvalidResponseError(
            "Tencent memory contains a malformed framework record"
        ) from error


def memory_fingerprint(record: MemoryRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"idempotency_key"})
    encoded = _encode(payload).encode()
    return hashlib.sha256(encoded).hexdigest()


def _client_filters(filters: dict[str, Any]) -> dict[str, str | None]:
    mapped: dict[str, str | None] = {"time_start": None, "time_end": None}
    for key in _PROVIDER_FILTERS:
        value = filters.get(key)
        if value is not None and not isinstance(value, str):
            raise TencentMemoryInvalidResponseError(
                f"Tencent memory filter {key!r} must be a string"
            )
        mapped[key] = value
    return mapped


def _metadata_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if key not in _PROVIDER_FILTERS}


def _identifier(prefix: str, value: str) -> str:
    raw = f"{prefix}:{value}"
    normalized = re.sub(r"[^a-zA-Z0-9._:/-]", "-", raw)
    if len(normalized) <= 240:
        return normalized
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{normalized[:223]}:{digest}"


def _redact_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(key, item) for key, item in value.items()}


def _redact_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value


def _redact_text(value: str) -> str:
    redacted = value
    redacted = _SENSITIVE_TEXT[0].sub("Bearer [REDACTED]", redacted)
    redacted = _SENSITIVE_TEXT[1].sub("[REDACTED]", redacted)
    redacted = _SENSITIVE_TEXT[2].sub(r"\1=[REDACTED]", redacted)
    return redacted


def _encode(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise TencentMemoryInvalidResponseError(
            "framework memory contains non-serializable metadata"
        ) from error
