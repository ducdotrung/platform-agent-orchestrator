from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deploy import generate_secrets, smoke
from platform_agent_orchestrator.api import create_app
from platform_agent_orchestrator.persistence import DatabaseReplayStore
from platform_agent_orchestrator.runtime import _runtime_settings
from platform_agent_orchestrator.settings import RuntimeRole

ROOT = Path(__file__).resolve().parents[1]


def test_image_compose_and_ci_keep_runtime_boundary_hardened() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    lock_lines = (ROOT / "requirements.lock").read_text().splitlines()

    assert "USER 10001:10001" in dockerfile
    assert "python:3.12.11-slim-bookworm" in dockerfile
    assert "requirements.lock" in dockerfile
    api = compose["services"]["api"]
    worker = compose["services"]["worker"]
    assert api["ports"] == ["127.0.0.1:8080:8080"]
    assert api["read_only"] is True and worker["read_only"] is True
    assert api["cap_drop"] == ["ALL"] and worker["cap_drop"] == ["ALL"]
    assert "webhook_signing_secret" not in worker["secrets"]
    assert compose["networks"]["backend"]["internal"] is True
    assert "service_completed_successfully" in (ROOT / "compose.yaml").read_text()
    assert "docker compose up --detach --wait api worker" in workflow
    assert "TEST_POSTGRES_URL" in workflow
    assert "python -m deploy.app_migrate" in workflow
    assert "checkpoint_migrate_main" in workflow
    assert all(
        "==" in line
        for line in lock_lines
        if line and not line.startswith(("#", " "))
    )


def test_runtime_settings_construct_urls_from_secret_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "database"
    webhook = tmp_path / "webhook"
    reviewer = tmp_path / "reviewer"
    database.write_text("database password\n")
    webhook.write_text("w" * 40)
    reviewer.write_text("r" * 40)
    values = {
        "PLATFORM_PROFILE": "local",
        "PLATFORM_RUNTIME_ROLE": "api",
        "ORCHESTRATOR_DATABASE_PASSWORD_FILE": str(database),
        "PLATFORM_WEBHOOK_SIGNING_SECRET_FILE": str(webhook),
        "PLATFORM_REVIEWER_SIGNING_SECRET_FILE": str(reviewer),
    }
    for key in tuple(os.environ):
        if key.startswith(("PLATFORM_", "ORCHESTRATOR_", "CHECKPOINT_")):
            monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    settings = _runtime_settings()

    assert settings.role == RuntimeRole.API
    assert settings.database_url is not None
    assert "database%20password" in settings.database_url.get_secret_value()
    assert settings.checkpoint_database_url is not None
    assert settings.webhook_signing_secret is not None
    assert "database password" not in repr(settings)


def test_secret_generator_is_idempotent_and_owner_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    generate_secrets.main()
    first = (tmp_path / ".local-secrets/database_password").read_text()
    generate_secrets.main()

    assert (tmp_path / ".local-secrets/database_password").read_text() == first
    for path in (tmp_path / ".local-secrets").iterdir():
        assert path.stat().st_mode & 0o077 == 0


def test_database_replay_claim_is_durable(tmp_path: Path) -> None:
    database = tmp_path / "replay.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database}",
        execution_options={"schema_translate_map": {"orchestrator": None}},
    )
    store = DatabaseReplayStore(async_sessionmaker(engine, expire_on_commit=False))

    async def scenario() -> None:
        from datetime import UTC, datetime, timedelta

        expires = datetime.now(UTC) + timedelta(minutes=5)
        values = {
            "authenticator_id": "sample",
            "nonce_hash": "ab" * 32,
            "request_fingerprint": "cd" * 32,
            "expires_at": expires,
        }
        assert await store.claim(**values) is True
        assert await store.claim(**values) is False
        await engine.dispose()

    asyncio.run(scenario())


def test_api_lifespan_runs_async_shutdown() -> None:
    stopped = False

    async def shutdown() -> None:
        nonlocal stopped
        stopped = True

    with TestClient(create_app(async_shutdown=shutdown)) as client:
        assert client.get("/livez").status_code == 200

    assert stopped is True


def test_smoke_waits_for_durable_worker_success(monkeypatch) -> None:
    responses = iter(
        [
            {"status": "queued"},
            {"status": "running"},
            {"status": "succeeded"},
        ]
    )
    requests: list[dict[str, Any]] = []

    def request_json(**values: Any) -> dict[str, Any]:
        requests.append(values)
        return next(responses)

    monkeypatch.setattr(smoke, "_request_json", request_json)
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)

    smoke.wait_for_success(
        base_url="http://sample",
        secret="s" * 40,
        run_id="run-123",
        timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert len(requests) == 3
    assert all(request["method"] == "GET" for request in requests)
    assert all(request["path"] == "/v1/runs/run-123" for request in requests)


def test_smoke_fails_on_non_success_terminal_state(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "_request_json",
        lambda **_values: {"status": "failed_terminal"},
    )

    with pytest.raises(RuntimeError, match="failed_terminal"):
        smoke.wait_for_success(
            base_url="http://sample",
            secret="s" * 40,
            run_id="run-123",
            timeout_seconds=1,
        )


def test_smoke_uses_fresh_nonce_for_each_authenticated_read(monkeypatch) -> None:
    nonces = iter(("A" * 22, "B" * 22))
    monkeypatch.setattr(smoke.secrets, "token_urlsafe", lambda _size: next(nonces))
    monkeypatch.setattr(smoke.time, "time", lambda: 1_700_000_000)

    first = smoke._signed_headers(
        secret="s" * 40,
        method="GET",
        path="/v1/runs/run-123",
        body=b"",
    )
    second = smoke._signed_headers(
        secret="s" * 40,
        method="GET",
        path="/v1/runs/run-123",
        body=b"",
    )

    assert first["X-Webhook-Nonce"] != second["X-Webhook-Nonce"]
    assert first["X-Webhook-Signature"] != second["X-Webhook-Signature"]
