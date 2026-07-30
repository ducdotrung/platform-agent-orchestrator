from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_agent_orchestrator.api import create_app
from platform_agent_orchestrator.contracts import AlertReceivedPayloadV1, EventEnvelopeV1
from platform_agent_orchestrator.persistence import (
    ApprovalConflict,
    ApprovalExpired,
    ApprovalStale,
    EventRepository,
)
from platform_agent_orchestrator.security import (
    AuthorizationContext,
    InMemoryReplayStore,
    ReviewerAuthorizationContext,
    ReviewerSecurity,
    reviewer_signature,
)
from platform_agent_orchestrator.service_contracts import (
    ApprovalDecision,
    ApprovalDecisionRequestV1,
)
from platform_agent_orchestrator.settings import ApplicationSettings

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
SECRET = "sample-reviewer-secret-with-enough-entropy"
ACTION_HASH = "ab" * 32


def migration_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def alert(key: str) -> EventEnvelopeV1:
    return EventEnvelopeV1(
        source="sample-sre-alert-agent",
        subject="orders-high-errors",
        idempotency_key=key,
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


def reviewer_headers(
    *,
    path: str,
    body: bytes,
    nonce: str,
    reviewer_id: str = "sample-reviewer",
) -> dict[str, str]:
    timestamp = str(int(NOW.timestamp()))
    signature = reviewer_signature(
        secret=SECRET,
        reviewer_id=reviewer_id,
        timestamp=timestamp,
        nonce=nonce,
        method="POST" if body else "GET",
        path=path,
        scope_id="sock-shop-sample",
        body=body,
    )
    return {
        "content-type": "application/json",
        "x-reviewer-id": reviewer_id,
        "x-reviewer-timestamp": timestamp,
        "x-reviewer-nonce": nonce,
        "x-reviewer-signature": signature,
        "x-team-scope": "sock-shop-sample",
    }


async def seed_waiting(
    repository: EventRepository,
    *,
    key: str,
    expires_at: datetime,
) -> str:
    admission = await repository.admit_event(
        alert(key),
        AuthorizationContext(actor_id="sample-sre-alert-agent", scope_id="sock-shop-sample"),
    )
    claim = (await repository.claim_jobs("worker-approval-test"))[0]
    summary = json.dumps(
        {
            "status": "interrupted",
            "interrupted": True,
            "approval": {
                "approval_version": 1,
                "kind": "alert_review",
                "action_hash": ACTION_HASH,
                "expires_at": expires_at.isoformat(),
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    await repository.record_interruption(claim, summary)
    return admission.run_id


def request_for(item: dict[str, object], **changes: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": "1",
        "approval_version": item["approval_version"],
        "run_version": item["run_version"],
        "decision": "approved",
        "reason": "Reviewed synthetic evidence and action",
        "action_hash": item["action_hash"],
        "idempotency_key": f"approval:{item['run_id']}:1",
    }
    request.update(changes)
    return request


def test_authenticated_list_approve_and_enqueue_resume(tmp_path: Path) -> None:
    database = tmp_path / "approval-api.db"
    command.upgrade(migration_config(f"sqlite:///{database}"), "head")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database}",
        execution_options={"schema_translate_map": {"orchestrator": None}},
    )
    repository = EventRepository(
        async_sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW
    )
    run_id = asyncio.run(
        seed_waiting(repository, key="sample:approval:api", expires_at=NOW + timedelta(minutes=15))
    )
    settings = ApplicationSettings.from_env({"PLATFORM_REVIEWER_SIGNING_SECRET": SECRET})
    reviewer_security = ReviewerSecurity(
        settings=settings,
        replay_store=InMemoryReplayStore(clock=lambda: NOW),
        clock=lambda: NOW,
    )
    app = create_app(
        settings=settings,
        reviewer_security=reviewer_security,
        event_repository=repository,
    )

    try:
        with TestClient(app) as client:
            listing = client.get(
                "/v1/approvals",
                headers=reviewer_headers(path="/v1/approvals", body=b"", nonce="A" * 22),
            )
            item = listing.json()["items"][0]
            request = request_for(item)
            body = json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
            path = f"/v1/runs/{run_id}/approvals"
            approved = client.post(
                path,
                content=body,
                headers=reviewer_headers(path=path, body=body, nonce="B" * 22),
            )
            repeated = client.post(
                path,
                content=body,
                headers=reviewer_headers(path=path, body=body, nonce="C" * 22),
            )
            unauthorized = client.get(
                "/v1/approvals",
                headers=reviewer_headers(
                    path="/v1/approvals",
                    body=b"",
                    nonce="D" * 22,
                    reviewer_id="intruder",
                ),
            )

        assert listing.status_code == 200
        assert item["run_id"] == run_id
        assert approved.status_code == 202
        assert approved.json()["actor_id"] == "sample-reviewer"
        assert repeated.status_code == 409
        assert repeated.json()["error"]["code"] == "approval_conflict"
        assert unauthorized.status_code == 403

        async def verify_resume() -> None:
            claim = (await repository.claim_jobs("resume-worker"))[0]
            assert claim.kind == "resume"
            decision = await repository.load_claimed_resume(claim)
            assert decision == {
                "approved": True,
                "actor": "sample-reviewer",
                "reason": "Reviewed synthetic evidence and action",
            }

        asyncio.run(verify_resume())
    finally:
        asyncio.run(engine.dispose())


def test_stale_altered_and_expired_approvals_are_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = tmp_path / "approval-rejections.db"
        command.upgrade(migration_config(f"sqlite:///{database}"), "head")
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{database}",
            execution_options={"schema_translate_map": {"orchestrator": None}},
        )
        repository = EventRepository(
            async_sessionmaker(engine, expire_on_commit=False), clock=lambda: NOW
        )
        authorization = ReviewerAuthorizationContext(
            actor_id="sample-reviewer", scope_id="sock-shop-sample"
        )
        try:
            stale_run = await seed_waiting(
                repository,
                key="sample:approval:stale",
                expires_at=NOW + timedelta(minutes=15),
            )
            stale = (await repository.list_pending_approvals("sock-shop-sample"))[0]
            with pytest.raises(ApprovalStale):
                await repository.decide_approval(
                    stale_run,
                    ApprovalDecisionRequestV1(
                        approval_version=1,
                        run_version=stale.run_version - 1,
                        decision=ApprovalDecision.APPROVED,
                        reason="Stale review",
                        action_hash=stale.action_hash,
                        idempotency_key="approval:stale",
                    ),
                    authorization,
                )
            with pytest.raises(ApprovalConflict):
                await repository.decide_approval(
                    stale_run,
                    ApprovalDecisionRequestV1(
                        approval_version=1,
                        run_version=stale.run_version,
                        decision=ApprovalDecision.APPROVED,
                        reason="Altered review",
                        action_hash="cd" * 32,
                        idempotency_key="approval:altered",
                    ),
                    authorization,
                )

            expired_run = await seed_waiting(
                repository,
                key="sample:approval:expired",
                expires_at=NOW - timedelta(seconds=1),
            )
            pending = await repository.list_pending_approvals("sock-shop-sample")
            expired = next(item for item in pending if item.run_id == expired_run)
            with pytest.raises(ApprovalExpired):
                await repository.decide_approval(
                    expired_run,
                    ApprovalDecisionRequestV1(
                        approval_version=1,
                        run_version=expired.run_version,
                        decision=ApprovalDecision.APPROVED,
                        reason="Expired review",
                        action_hash=expired.action_hash,
                        idempotency_key="approval:expired",
                    ),
                    authorization,
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())
