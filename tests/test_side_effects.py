from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

from platform_agent_orchestrator.adapters import DemoAdapters
from platform_agent_orchestrator.adapters.demo import DemoNotifier
from platform_agent_orchestrator.bootstrap import build_dependencies
from platform_agent_orchestrator.core import DomainEvent
from platform_agent_orchestrator.persistence import SideEffectRecord
from platform_agent_orchestrator.runtime import RunMetadata
from platform_agent_orchestrator.settings import ApplicationSettings
from platform_agent_orchestrator.side_effects import (
    AmbiguousSideEffect,
    DatabaseSideEffectStore,
    DurableNotifier,
    SideEffectConflict,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
RUN_ID = "00000000-0000-4000-8000-000000000001"


def migration_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def store_for(tmp_path: Path) -> tuple[DatabaseSideEffectStore, sa.Engine, list[datetime]]:
    database = tmp_path / "side-effects.db"
    command.upgrade(migration_config(f"sqlite:///{database}"), "head")
    engine = sa.create_engine(
        f"sqlite:///{database}",
        execution_options={"schema_translate_map": {"orchestrator": None}},
    )
    sessions = sessionmaker(engine, expire_on_commit=False)
    clock = [NOW]
    return DatabaseSideEffectStore(sessions, clock=lambda: clock[0]), engine, clock


def test_duplicate_node_execution_returns_one_logical_notification(tmp_path: Path) -> None:
    store, engine, _clock = store_for(tmp_path)
    try:
        provider = DemoNotifier()
        notifier = DurableNotifier(store, provider, "sock-shop-sample")

        first = notifier.send(
            "sre-alerts", "Investigate orders", idempotency_key="alert:1", run_id=RUN_ID
        )
        second = notifier.send(
            "sre-alerts", "Investigate orders", idempotency_key="alert:1", run_id=RUN_ID
        )

        assert first == second
        assert len(provider.messages) == 1
        with Session(engine) as session:
            effect = session.scalar(sa.select(SideEffectRecord))
            assert effect is not None and effect.status == "succeeded"
            assert effect.attempt_count == 1
    finally:
        engine.dispose()


def test_changed_request_with_same_key_is_rejected(tmp_path: Path) -> None:
    store, engine, _clock = store_for(tmp_path)
    try:
        notifier = DurableNotifier(store, DemoNotifier(), "sock-shop-sample")
        notifier.send("sre-alerts", "First", idempotency_key="alert:1", run_id=RUN_ID)

        with pytest.raises(SideEffectConflict):
            notifier.send("sre-alerts", "Changed", idempotency_key="alert:1", run_id=RUN_ID)
    finally:
        engine.dispose()


def test_expired_claim_becomes_unknown_and_is_not_blindly_retried(tmp_path: Path) -> None:
    store, engine, clock = store_for(tmp_path)
    try:
        store.reserve_notification(
            scope_id="sock-shop-sample",
            run_id=RUN_ID,
            channel="sre-alerts",
            message="Investigate orders",
            idempotency_key="alert:1",
            provider="demo-notifier",
        )
        clock[0] += timedelta(seconds=31)
        provider = DemoNotifier()

        with pytest.raises(AmbiguousSideEffect):
            DurableNotifier(store, provider, "sock-shop-sample").send(
                "sre-alerts",
                "Investigate orders",
                idempotency_key="alert:1",
                run_id=RUN_ID,
            )

        assert not provider.messages
        with Session(engine) as session:
            effect = session.scalar(sa.select(SideEffectRecord))
            assert effect is not None and effect.status == "unknown"
    finally:
        engine.dispose()


def test_alert_capability_uses_durable_composed_notifier(tmp_path: Path) -> None:
    store, engine, _clock = store_for(tmp_path)
    demo = DemoAdapters()
    durable = DurableNotifier(store, demo.notifier, "sock-shop-sample")
    dependencies = build_dependencies(
        ApplicationSettings(),
        demo=demo,
        notifier=durable,
    )
    event = DomainEvent(
        id="durable-alert-event",
        type="monitoring.alert.received",
        source="sample-sre-alert-agent",
        subject="orders-high-errors",
        occurred_at=NOW,
        correlation_id="durable-alert-correlation",
        idempotency_key="sample:orders:durable",
        tenant_id="sock-shop-sample",
        data={
            "alert_id": "orders-high-errors",
            "title": "Orders errors",
            "service": "orders",
            "severity": "critical",
            "environment": "sample",
            "count": 42,
            "users": 7,
        },
    )
    run = RunMetadata(
        run_id=RUN_ID,
        flow_name="alert",
        flow_version="2.0.0",
        thread_id=RUN_ID,
        correlation_id=event.correlation_id,
        tenant_id=event.tenant_id,
        status="running",
    )
    try:
        first = asyncio.run(dependencies.dispatcher().execute(run, event))
        second = asyncio.run(dependencies.dispatcher().execute(run, event))

        assert first.output["notification_receipt"] == second.output[
            "notification_receipt"
        ]
        assert len(demo.notifier.messages) == 1
    finally:
        dependencies.shutdown()
        engine.dispose()
