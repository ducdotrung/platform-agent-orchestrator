from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_agent_orchestrator.api import create_app
from platform_agent_orchestrator.persistence import EventRepository
from platform_agent_orchestrator.security import (
    AdmissionSecurity,
    InMemoryReplayStore,
    webhook_signature,
)
from platform_agent_orchestrator.settings import ApplicationSettings

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
SECRET = "sample-test-secret-with-sufficient-entropy"


def event_body(*, title: str = "Orders error rate is high") -> bytes:
    return json.dumps(
        {
            "schema_version": "1",
            "type": "monitoring.alert.received",
            "source": "sample-sre-alert-agent",
            "subject": "orders-high-errors",
            "idempotency_key": "sample:orders-high-errors:2026-07-30T12",
            "payload": {
                "alert_id": "orders-high-errors",
                "title": title,
                "service": "orders",
                "severity": "critical",
                "environment": "sample",
                "count": 42,
                "users": 7,
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def headers(*, path: str, body: bytes, nonce: str) -> dict[str, str]:
    timestamp = str(int(NOW.timestamp()))
    signature = webhook_signature(
        secret=SECRET,
        key_id="sample-sre-alert-agent",
        timestamp=timestamp,
        nonce=nonce,
        method="POST" if body else "GET",
        path=path,
        workflow="alert",
        scope_id="sock-shop-sample",
        body=body,
    )
    return {
        "content-type": "application/json",
        "x-webhook-key-id": "sample-sre-alert-agent",
        "x-webhook-timestamp": timestamp,
        "x-webhook-nonce": nonce,
        "x-webhook-signature": signature,
        "x-workflow": "alert",
        "x-team-scope": "sock-shop-sample",
    }


def test_authenticated_admission_duplicate_conflict_and_run_lookup(tmp_path: Path) -> None:
    database = tmp_path / "admission-api.db"
    sync_url = f"sqlite:///{database}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(config, "head")

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database}",
        execution_options={"schema_translate_map": {"orchestrator": None}},
    )
    repository = EventRepository(
        async_sessionmaker(engine, expire_on_commit=False),
        clock=lambda: NOW,
    )
    settings = ApplicationSettings.from_env(
        {"PLATFORM_WEBHOOK_SIGNING_SECRET": SECRET}
    )
    security = AdmissionSecurity(
        settings=settings,
        replay_store=InMemoryReplayStore(clock=lambda: NOW),
        clock=lambda: NOW,
    )
    app = create_app(
        settings=settings,
        admission_security=security,
        event_repository=repository,
    )
    body = event_body()

    try:
        with TestClient(app) as client:
            first = client.post(
                "/v1/events",
                content=body,
                headers=headers(path="/v1/events", body=body, nonce="A" * 22),
            )
            duplicate = client.post(
                "/v1/events",
                content=body,
                headers=headers(path="/v1/events", body=body, nonce="B" * 22),
            )
            changed = event_body(title="Changed content")
            conflict = client.post(
                "/v1/events",
                content=changed,
                headers=headers(path="/v1/events", body=changed, nonce="C" * 22),
            )
            run_id = first.json()["run_id"]
            run_path = f"/v1/runs/{run_id}"
            run = client.get(
                run_path,
                headers=headers(path=run_path, body=b"", nonce="D" * 22),
            )
            ready = client.get("/readyz")

        assert first.status_code == 202
        assert duplicate.status_code == 200
        assert duplicate.json()["run_id"] == first.json()["run_id"]
        assert duplicate.json()["duplicate"] is True
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"
        assert run.status_code == 200
        assert run.json()["run_id"] == run_id
        assert run.json()["status"] == "queued"
        assert ready.status_code == 200
    finally:
        asyncio.run(engine.dispose())
