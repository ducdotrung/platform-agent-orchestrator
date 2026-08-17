from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_agent_orchestrator.api import create_app
from platform_agent_orchestrator.bootstrap import RuntimeDependencies
from platform_agent_orchestrator.contracts import AlertReceivedPayloadV1, EventEnvelopeV1
from platform_agent_orchestrator.observability.base import WorkflowTrace
from platform_agent_orchestrator.persistence import EventRepository, FeedbackRecord
from platform_agent_orchestrator.security import (
    AuthorizationContext,
    InMemoryReplayStore,
    ReviewerSecurity,
    reviewer_signature,
)
from platform_agent_orchestrator.service_contracts import FeedbackRequestV1
from platform_agent_orchestrator.settings import ApplicationSettings

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
SECRET = "sample-reviewer-secret-with-enough-entropy"


class UnavailableTelemetry:
    def __init__(self) -> None:
        self.score_attempts: list[tuple[str, str, object]] = []

    def trace_workflow(self, *_args: object) -> Any:
        return nullcontext(WorkflowTrace())

    def score(self, trace_id: str, name: str, value: object, **_kwargs: object) -> None:
        self.score_attempts.append((trace_id, name, value))
        raise RuntimeError("telemetry unavailable")

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def migration_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def feedback_headers(path: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(NOW.timestamp()))
    nonce = "F" * 22
    return {
        "content-type": "application/json",
        "x-reviewer-id": "sample-reviewer",
        "x-reviewer-timestamp": timestamp,
        "x-reviewer-nonce": nonce,
        "x-reviewer-signature": reviewer_signature(
            secret=SECRET,
            reviewer_id="sample-reviewer",
            timestamp=timestamp,
            nonce=nonce,
            method="POST",
            path=path,
            scope_id="sock-shop-sample",
            body=body,
        ),
        "x-team-scope": "sock-shop-sample",
    }


def test_feedback_is_authoritative_when_telemetry_is_unavailable(tmp_path: Path) -> None:
    database = tmp_path / "feedback.db"
    command.upgrade(migration_config(f"sqlite:///{database}"), "head")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database}",
        execution_options={"schema_translate_map": {"orchestrator": None}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = EventRepository(sessions, clock=lambda: NOW)
    event = EventEnvelopeV1(
        source="sample-sre-alert-agent",
        subject="orders-high-errors",
        idempotency_key="sample:feedback:1",
        payload=AlertReceivedPayloadV1(
            alert_id="orders-high-errors",
            title="Orders errors",
            service="orders",
            severity="critical",
            environment="sample",
            count=42,
            users=7,
        ),
    )
    run_id = asyncio.run(
        repository.admit_event(
            event,
            AuthorizationContext(
                actor_id="sample-sre-alert-agent", scope_id="sock-shop-sample"
            ),
        )
    ).run_id
    settings = ApplicationSettings.from_env({"PLATFORM_REVIEWER_SIGNING_SECRET": SECRET})
    telemetry = UnavailableTelemetry()
    dependencies = RuntimeDependencies(
        settings=settings,
        observability=telemetry,
    )
    security = ReviewerSecurity(
        settings=settings,
        replay_store=InMemoryReplayStore(clock=lambda: NOW),
        clock=lambda: NOW,
    )
    app = create_app(
        dependencies=dependencies,
        reviewer_security=security,
        event_repository=repository,
    )
    request = {
        "schema_version": "1",
        "rating": "helpful",
        "reason": "The cited Sock Shop dependency was useful",
        "trace_id": "trace-public-1",
        "metadata": {"surface": "review"},
    }
    body = json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    path = f"/v1/runs/{run_id}/feedback"

    try:
        with TestClient(app) as client:
            response = client.post(path, content=body, headers=feedback_headers(path, body))

        assert response.status_code == 201
        assert response.json()["trace_id"] == "trace-public-1"
        assert telemetry.score_attempts == [
            ("trace-public-1", "feedback.rating", "helpful")
        ]

        async def verify_record() -> None:
            async with sessions() as session:
                record = await session.scalar(sa.select(FeedbackRecord))
                assert record is not None
                assert record.run_id == run_id
                assert record.trace_id == "trace-public-1"
                created_at = record.created_at.replace(tzinfo=UTC)
                retention = record.retention_until.replace(tzinfo=UTC)
                assert (retention - created_at).days == 90

        asyncio.run(verify_record())
    finally:
        asyncio.run(engine.dispose())


def test_feedback_rejects_sensitive_or_oversized_metadata() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequestV1(
            rating="unsafe",
            reason="Sensitive field",
            metadata={"nested": {"api_key": "do-not-store"}},
        )
    with pytest.raises(ValidationError):
        FeedbackRequestV1(
            rating="not_helpful",
            reason="Oversized metadata",
            metadata={"value": "x" * 8_192},
        )
