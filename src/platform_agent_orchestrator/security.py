"""Deterministic signed-webhook authentication and admission authorization."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from platform_agent_orchestrator.contracts import EventEnvelopeV1
from platform_agent_orchestrator.settings import ApplicationSettings, DeploymentProfile

_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
_SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AdmissionSecurityError(Exception):
    def __init__(self, status_code: int, code: str, public_message: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.public_message = public_message


class ReplayStoreUnavailable(RuntimeError):
    pass


class ReplayStore(Protocol):
    async def claim(
        self,
        *,
        authenticator_id: str,
        nonce_hash: str,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> bool: ...


@dataclass(frozen=True)
class _ReplayEntry:
    request_fingerprint: str
    expires_at: datetime


class InMemoryReplayStore:
    """Process-local fence for demo/tests; local services require a durable store."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        max_entries: int = 10_000,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_entries = max_entries
        self._entries: dict[tuple[str, str], _ReplayEntry] = {}
        self._lock = asyncio.Lock()

    async def claim(
        self,
        *,
        authenticator_id: str,
        nonce_hash: str,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> bool:
        async with self._lock:
            now = self._clock()
            self._entries = {
                key: entry for key, entry in self._entries.items() if entry.expires_at > now
            }
            key = (authenticator_id, nonce_hash)
            if key in self._entries:
                return False
            if len(self._entries) >= self._max_entries:
                raise ReplayStoreUnavailable("demo replay store capacity reached")
            self._entries[key] = _ReplayEntry(request_fingerprint, expires_at)
            return True


class UnavailableReplayStore:
    async def claim(
        self,
        *,
        authenticator_id: str,
        nonce_hash: str,
        request_fingerprint: str,
        expires_at: datetime,
    ) -> bool:
        raise ReplayStoreUnavailable("durable replay store is not initialized")


class AuthorizationContext(BaseModel):
    """Bounded authorization result safe to copy into workflow state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_type: Literal["service"] = "service"
    actor_id: str = Field(min_length=1, max_length=128)
    scope_id: str = Field(min_length=1, max_length=128)
    workflow: Literal["alert"] = "alert"
    permissions: tuple[Literal["events:write"], ...] = ("events:write",)
    policy_version: Literal["sample-admission-v1"] = "sample-admission-v1"


def webhook_signature(
    *,
    secret: str,
    key_id: str,
    timestamp: str,
    nonce: str,
    method: str,
    path: str,
    workflow: str,
    scope_id: str,
    body: bytes,
) -> str:
    body_digest = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        (
            "v1",
            key_id,
            timestamp,
            nonce,
            method.upper(),
            path,
            workflow,
            scope_id,
            body_digest,
        )
    ).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class AdmissionSecurity:
    settings: ApplicationSettings
    replay_store: ReplayStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    @classmethod
    def from_settings(cls, settings: ApplicationSettings) -> AdmissionSecurity:
        if settings.profile == DeploymentProfile.DEMO:
            replay_store: ReplayStore = InMemoryReplayStore()
        else:
            replay_store = UnavailableReplayStore()
        return cls(settings=settings, replay_store=replay_store)

    async def authorize_request(self, request: Request) -> AuthorizationContext:
        secret = self.settings.webhook_signing_secret
        if secret is None:
            raise AdmissionSecurityError(
                503,
                "admission_security_unavailable",
                "Admission authentication is not configured",
            )
        content_type = request.headers.get("content-type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            raise AdmissionSecurityError(415, "content_type_unsupported", "JSON is required")

        key_id = self._required_header(request, "x-webhook-key-id", max_length=128)
        timestamp = self._required_header(request, "x-webhook-timestamp", max_length=16)
        nonce = self._required_header(request, "x-webhook-nonce", max_length=128)
        supplied_signature = self._required_header(
            request, "x-webhook-signature", max_length=64
        )
        workflow = self._required_header(request, "x-workflow", max_length=32)
        scope_id = self._required_header(request, "x-team-scope", max_length=128)

        if not timestamp.isascii() or not timestamp.isdigit():
            self._unauthenticated()
        signed_at = int(timestamp)
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("security clock must return a timezone-aware datetime")
        if abs(int(now.timestamp()) - signed_at) > self.settings.webhook_max_skew_seconds:
            self._unauthenticated()
        if _NONCE_PATTERN.fullmatch(nonce) is None:
            self._unauthenticated()
        if _SIGNATURE_PATTERN.fullmatch(supplied_signature) is None:
            self._unauthenticated()

        body = await request.body()
        expected_signature = webhook_signature(
            secret=secret.get_secret_value(),
            key_id=key_id,
            timestamp=timestamp,
            nonce=nonce,
            method=request.method,
            path=request.url.path,
            workflow=workflow,
            scope_id=scope_id,
            body=body,
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            self._unauthenticated()

        try:
            envelope = EventEnvelopeV1.model_validate_json(body)
        except ValidationError as error:
            raise AdmissionSecurityError(
                422, "event_validation_failed", "Event validation failed"
            ) from error

        if key_id not in self.settings.allowed_sources or envelope.source != key_id:
            self._forbidden()
        if workflow != "alert" or envelope.type != "alert.received":
            self._forbidden()
        if scope_id != self.settings.scope_id:
            self._forbidden()
        if envelope.payload.service not in self.settings.allowed_services:
            self._forbidden()

        nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
        request_fingerprint = hashlib.sha256(
            (
                f"{key_id}\n{timestamp}\n{nonce}\n{request.method}\n{request.url.path}\n"
                f"{workflow}\n{scope_id}\n"
            ).encode()
            + body
        ).hexdigest()
        try:
            claimed = await self.replay_store.claim(
                authenticator_id=key_id,
                nonce_hash=nonce_hash,
                request_fingerprint=request_fingerprint,
                expires_at=now + timedelta(seconds=self.settings.webhook_nonce_ttl_seconds),
            )
        except ReplayStoreUnavailable as error:
            raise AdmissionSecurityError(
                503, "replay_protection_unavailable", "Replay protection is unavailable"
            ) from error
        if not claimed:
            raise AdmissionSecurityError(409, "webhook_replayed", "Webhook replay rejected")

        return AuthorizationContext(
            actor_id=key_id,
            scope_id=scope_id,
        )

    @staticmethod
    def _required_header(request: Request, name: str, *, max_length: int) -> str:
        value = request.headers.get(name)
        if value is None or not value or len(value) > max_length or value != value.strip():
            AdmissionSecurity._unauthenticated()
        return value

    @staticmethod
    def _unauthenticated() -> None:
        raise AdmissionSecurityError(
            401, "webhook_unauthenticated", "Webhook authentication failed"
        )

    @staticmethod
    def _forbidden() -> None:
        raise AdmissionSecurityError(
            403, "admission_forbidden", "Event is outside the allowed scope"
        )


async def require_admission_authorization(request: Request) -> AuthorizationContext:
    security: AdmissionSecurity = request.app.state.admission_security
    return await security.authorize_request(request)
