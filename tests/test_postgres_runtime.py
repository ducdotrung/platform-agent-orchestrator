from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from platform_agent_orchestrator.adapters import DemoAdapters
from platform_agent_orchestrator.bootstrap import build_dependencies
from platform_agent_orchestrator.checkpointing import postgres_checkpointer
from platform_agent_orchestrator.contracts import AlertReceivedPayloadV1, EventEnvelopeV1
from platform_agent_orchestrator.persistence import EventRepository
from platform_agent_orchestrator.security import (
    AuthorizationContext,
    ReviewerAuthorizationContext,
)
from platform_agent_orchestrator.service_contracts import (
    ApprovalDecision,
    ApprovalDecisionRequestV1,
)
from platform_agent_orchestrator.settings import ApplicationSettings
from platform_agent_orchestrator.side_effects import DatabaseSideEffectStore, DurableNotifier
from platform_agent_orchestrator.worker import RegistryExecution

POSTGRES_CONFIGURED = {
    "TEST_POSTGRES_URL",
    "TEST_CHECKPOINT_POSTGRES_URL",
}.issubset(os.environ)


@pytest.mark.skipif(
    not POSTGRES_CONFIGURED,
    reason="set both PostgreSQL test URLs to run the real runtime integration",
)
def test_postgres_runtime_completes_durable_alert_and_approval_paths() -> None:
    async def scenario() -> None:
        database_url = os.environ["TEST_POSTGRES_URL"]
        checkpoint_url = os.environ["TEST_CHECKPOINT_POSTGRES_URL"]
        settings = ApplicationSettings.from_env(
            {
                "PLATFORM_PROFILE": "local",
                "PLATFORM_RUNTIME_ROLE": "worker",
                "ORCHESTRATOR_DATABASE_URL": database_url,
                "CHECKPOINT_DATABASE_URL": checkpoint_url,
            }
        )
        async_engine = create_async_engine(database_url)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        repository = EventRepository(sessions)
        sync_engine = sa.create_engine(database_url)
        side_effects = DatabaseSideEffectStore(
            sessionmaker(sync_engine, expire_on_commit=False)
        )
        demo = DemoAdapters()
        notifier = DurableNotifier(
            side_effects,
            demo.notifier,
            settings.scope_id,
        )
        dependencies = build_dependencies(settings, demo=demo, notifier=notifier)
        event = EventEnvelopeV1(
            source="sample-sre-alert-agent",
            subject="orders-high-errors",
            idempotency_key=f"sample:postgres-runtime:{uuid4()}",
            payload=AlertReceivedPayloadV1(
                alert_id="orders-high-errors",
                title="Synthetic orders error rate",
                service="orders",
                severity="critical",
                environment="sample",
                count=42,
                users=7,
            ),
        )
        authorization = AuthorizationContext(
            actor_id="sample-sre-alert-agent",
            scope_id=settings.scope_id,
        )
        try:
            admission = await repository.admit_event(event, authorization)
            claims = await repository.claim_jobs("postgres-test-worker", limit=32)
            claim = next(item for item in claims if item.run_id == admission.run_id)
            with postgres_checkpointer(checkpoint_url) as checkpointer:
                flow_dispatcher = dependencies.dispatcher(checkpointer=checkpointer)
                result = await RegistryExecution(repository, flow_dispatcher).execute(claim)
            await repository.record_success(
                claim,
                json.dumps(result.output, separators=(",", ":"), sort_keys=True),
            )
            run = await repository.get_run(admission.run_id, settings.scope_id)

            assert result.output["status"] == "notified"
            assert run is not None and run.status.value == "succeeded"

            approval_event = event.model_copy(
                update={
                    "id": str(uuid4()),
                    "correlation_id": str(uuid4()),
                    "idempotency_key": f"sample:postgres-approval:{uuid4()}",
                }
            )
            approval_admission = await repository.admit_event(
                approval_event,
                authorization,
            )
            approval_claims = await repository.claim_jobs(
                "postgres-approval-worker",
                limit=32,
            )
            approval_claim = next(
                item for item in approval_claims if item.run_id == approval_admission.run_id
            )
            action_hash = "ab" * 32
            expires_at = datetime.now(UTC) + timedelta(minutes=15)
            await repository.record_interruption(
                approval_claim,
                json.dumps(
                    {
                        "status": "interrupted",
                        "interrupted": True,
                        "approval": {
                            "approval_version": 1,
                            "kind": "alert_review",
                            "action_hash": action_hash,
                            "expires_at": expires_at.isoformat(),
                        },
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
            pending = next(
                item
                for item in await repository.list_pending_approvals(settings.scope_id)
                if item.run_id == approval_admission.run_id
            )
            decision = await repository.decide_approval(
                approval_admission.run_id,
                ApprovalDecisionRequestV1(
                    approval_version=pending.approval_version,
                    run_version=pending.run_version,
                    decision=ApprovalDecision.APPROVED,
                    reason="Real PostgreSQL integration review",
                    action_hash=pending.action_hash,
                    idempotency_key=f"approval:{approval_admission.run_id}:1",
                ),
                ReviewerAuthorizationContext(
                    actor_id="sample-reviewer",
                    scope_id=settings.scope_id,
                ),
            )

            assert decision.decision == ApprovalDecision.APPROVED
            resume_claims = await repository.claim_jobs(
                "postgres-resume-worker",
                limit=32,
            )
            assert any(
                item.run_id == approval_admission.run_id and item.kind == "resume"
                for item in resume_claims
            )
        finally:
            dependencies.shutdown()
            await async_engine.dispose()
            sync_engine.dispose()

    asyncio.run(scenario())
