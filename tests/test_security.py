from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from platform_agent_orchestrator.api import create_app
from platform_agent_orchestrator.security import (
    AdmissionSecurity,
    AuthorizationContext,
    InMemoryReplayStore,
    UnavailableReplayStore,
    require_admission_authorization,
    webhook_signature,
)
from platform_agent_orchestrator.settings import ApplicationSettings

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
SECRET = "sample-test-secret-with-sufficient-entropy"
PATH = "/v1/test-events"


def event_data() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "type": "monitoring.alert.received",
        "source": "sample-sre-alert-agent",
        "subject": "orders-high-errors",
        "idempotency_key": "sample:orders-high-errors:2026-07-30T12",
        "payload": {
            "alert_id": "orders-high-errors",
            "title": "Orders error rate is high",
            "service": "orders",
            "severity": "critical",
            "environment": "sample",
            "count": 42,
            "users": 7,
        },
    }


def encoded_event(data: dict[str, Any] | None = None) -> bytes:
    return json.dumps(data or event_data(), separators=(",", ":"), sort_keys=True).encode()


def settings(**overrides: str) -> ApplicationSettings:
    environ = {"PLATFORM_WEBHOOK_SIGNING_SECRET": SECRET, **overrides}
    return ApplicationSettings.from_env(environ)


def security_for(application_settings: ApplicationSettings) -> AdmissionSecurity:
    return AdmissionSecurity(
        settings=application_settings,
        replay_store=InMemoryReplayStore(clock=lambda: NOW),
        clock=lambda: NOW,
    )


def secured_app(
    application_settings: ApplicationSettings,
    security: AdmissionSecurity | None = None,
) -> FastAPI:
    app = create_app(
        settings=application_settings,
        admission_security=security or security_for(application_settings),
    )

    @app.post(PATH)
    async def protected(
        authorization: Annotated[
            AuthorizationContext,
            Depends(require_admission_authorization),
        ],
    ) -> dict[str, Any]:
        return authorization.model_dump(mode="json")

    return app


def signed_headers(
    body: bytes,
    *,
    nonce: str = "A" * 22,
    timestamp: str | None = None,
    key_id: str = "sample-sre-alert-agent",
    workflow: str = "alert",
    scope_id: str = "sock-shop-sample",
    secret: str = SECRET,
) -> dict[str, str]:
    signed_timestamp = timestamp or str(int(NOW.timestamp()))
    signature = webhook_signature(
        secret=secret,
        key_id=key_id,
        timestamp=signed_timestamp,
        nonce=nonce,
        method="POST",
        path=PATH,
        workflow=workflow,
        scope_id=scope_id,
        body=body,
    )
    return {
        "content-type": "application/json",
        "x-webhook-key-id": key_id,
        "x-webhook-timestamp": signed_timestamp,
        "x-webhook-nonce": nonce,
        "x-webhook-signature": signature,
        "x-workflow": workflow,
        "x-team-scope": scope_id,
    }


def test_signed_authorized_event_returns_bounded_context() -> None:
    body = encoded_event()
    app = secured_app(settings())

    with TestClient(app) as client:
        response = client.post(PATH, content=body, headers=signed_headers(body))

    assert response.status_code == 200
    assert response.json() == {
        "actor_type": "service",
        "actor_id": "sample-sre-alert-agent",
        "scope_id": "sock-shop-sample",
        "workflow": "alert",
        "permissions": ["events:write"],
        "policy_version": "sample-admission-v1",
    }
    assert SECRET not in response.text
    assert "signature" not in response.text


@pytest.mark.parametrize(
    ("header_change", "expected_status"),
    [
        ({"x-webhook-signature": "0" * 64}, 401),
        ({"x-webhook-nonce": "short"}, 401),
    ],
)
def test_invalid_webhook_authentication_is_rejected_without_details(
    header_change: dict[str, str], expected_status: int
) -> None:
    body = encoded_event()
    headers = signed_headers(body) | header_change

    with TestClient(secured_app(settings())) as client:
        response = client.post(PATH, content=body, headers=headers)

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == "webhook_unauthenticated"
    assert SECRET not in response.text


def test_correctly_signed_stale_webhook_is_rejected() -> None:
    body = encoded_event()
    stale = str(int((NOW - timedelta(hours=1)).timestamp()))

    with TestClient(secured_app(settings())) as client:
        response = client.post(
            PATH,
            content=body,
            headers=signed_headers(body, timestamp=stale),
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "webhook_unauthenticated"


@pytest.mark.parametrize(
    ("event_change", "header_options"),
    [
        ({"source": "unknown-producer"}, {}),
        ({"payload": {**event_data()["payload"], "service": "company-private"}}, {}),
        ({}, {"workflow": "engineering"}),
        ({}, {"scope_id": "another-team"}),
    ],
)
def test_source_workflow_team_and_service_authorization_is_exact(
    event_change: dict[str, Any], header_options: dict[str, str]
) -> None:
    data = event_data() | event_change
    body = encoded_event(data)
    headers = signed_headers(body, **header_options)

    with TestClient(secured_app(settings())) as client:
        response = client.post(PATH, content=body, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admission_forbidden"


def test_replayed_nonce_is_rejected_but_new_nonce_can_retry_business_event() -> None:
    body = encoded_event()
    app = secured_app(settings())

    with TestClient(app) as client:
        first = client.post(PATH, content=body, headers=signed_headers(body))
        replay = client.post(PATH, content=body, headers=signed_headers(body))
        safe_retry = client.post(
            PATH,
            content=body,
            headers=signed_headers(body, nonce="B" * 22),
        )

    assert first.status_code == 200
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "webhook_replayed"
    assert safe_retry.status_code == 200


def test_signed_invalid_event_is_rejected_before_replay_claim() -> None:
    body = b'{"schema_version":"2"}'
    app = secured_app(settings())

    with TestClient(app) as client:
        first = client.post(PATH, content=body, headers=signed_headers(body))
        second = client.post(PATH, content=body, headers=signed_headers(body))

    assert first.status_code == 422
    assert second.status_code == 422
    assert first.json()["error"]["code"] == "event_validation_failed"
    assert body.decode() not in first.text


def test_missing_secret_and_local_non_durable_replay_store_fail_closed() -> None:
    body = encoded_event()
    missing_secret = secured_app(ApplicationSettings())
    local_settings = settings(
        PLATFORM_PROFILE="local",
        PLATFORM_RUNTIME_ROLE="api",
        ORCHESTRATOR_DATABASE_URL="postgresql://sample:secret@db/app",
    )
    local_security = AdmissionSecurity(
        settings=local_settings,
        replay_store=UnavailableReplayStore(),
        clock=lambda: NOW,
    )
    local_app = create_app(
        settings=local_settings,
        admission_security=local_security,
    )

    @local_app.post(PATH)
    async def local_protected(
        _authorization: Annotated[
            AuthorizationContext,
            Depends(require_admission_authorization),
        ],
    ) -> dict[str, bool]:
        return {"accepted": True}

    with TestClient(missing_secret) as client:
        unconfigured = client.post(PATH, content=body, headers=signed_headers(body))
    with TestClient(local_app) as client:
        non_durable = client.post(PATH, content=body, headers=signed_headers(body))

    assert unconfigured.status_code == 503
    assert unconfigured.json()["error"]["code"] == "admission_security_unavailable"
    assert non_durable.status_code == 503
    assert non_durable.json()["error"]["code"] == "replay_protection_unavailable"


def test_ready_requires_authentication_configuration() -> None:
    with TestClient(create_app(settings=settings())) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["authentication"] == "ready"
    assert response.json()["checks"]["persistence"] == "unavailable"
