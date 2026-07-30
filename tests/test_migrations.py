from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from platform_agent_orchestrator.persistence import Base

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "approvals",
    "audit_events",
    "auth_replay_claims",
    "delivery_attempts",
    "delivery_jobs",
    "events",
    "feedback",
    "idempotency_claims",
    "runs",
    "side_effects",
}
NOW = datetime(2026, 7, 30, tzinfo=UTC)


def migration_config(url: str, *, output_buffer: StringIO | None = None) -> Config:
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output_buffer)
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def migrated_engine(tmp_path: Path) -> sa.Engine:
    database = tmp_path / "migration.db"
    url = f"sqlite:///{database}"
    command.upgrade(migration_config(url), "head")
    engine = sa.create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def event_values(*, event_id: str, key: str, fingerprint: bytes = b"f" * 32) -> dict:
    return {
        "id": event_id,
        "scope_id": "sock-shop-sample",
        "source": "sample-sre-alert-agent",
        "event_type": "alert.received",
        "schema_version": "1",
        "subject": "orders-high-errors",
        "occurred_at": NOW,
        "correlation_id": f"correlation-{event_id}",
        "idempotency_key": key,
        "fingerprint": fingerprint,
        "payload": {"service": "orders"},
    }


def test_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "upgrade.db"
    url = f"sqlite:///{database}"
    config = migration_config(url)

    command.upgrade(config, "head")
    engine = sa.create_engine(url)
    assert EXPECTED_TABLES <= set(sa.inspect(engine).get_table_names())

    command.downgrade(config, "base")
    assert not (EXPECTED_TABLES & set(sa.inspect(engine).get_table_names()))
    engine.dispose()


def test_postgresql_offline_upgrade_is_schema_qualified() -> None:
    output = StringIO()
    config = migration_config(
        "postgresql+psycopg://sample:unused@localhost/orchestrator",
        output_buffer=output,
    )

    command.upgrade(config, "head", sql=True)

    ddl = output.getvalue()
    assert "CREATE SCHEMA IF NOT EXISTS orchestrator" in ddl
    assert "CREATE TABLE orchestrator.events" in ddl
    assert "CREATE TABLE orchestrator.side_effects" in ddl
    assert "CREATE TABLE orchestrator.feedback" in ddl


def test_event_identity_and_payload_constraints(migrated_engine: sa.Engine) -> None:
    events = sa.Table("events", sa.MetaData(), autoload_with=migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            events.insert(),
            event_values(event_id="event-1", key="same-key"),
        )

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                events.insert(),
                event_values(event_id="event-2", key="same-key"),
            )

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                events.insert(),
                event_values(event_id="event-3", key="bad-hash", fingerprint=b"short"),
            )

    oversized = event_values(event_id="event-4", key="oversized")
    oversized["payload"] = {"title": "x" * 65_536}
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(events.insert(), oversized)


def test_replay_retention_and_uniqueness_constraints(migrated_engine: sa.Engine) -> None:
    replay = sa.Table("auth_replay_claims", sa.MetaData(), autoload_with=migrated_engine)
    valid = {
        "id": "claim-1",
        "authenticator_id": "sample-sre-alert-agent",
        "nonce_hash": b"n" * 32,
        "request_fingerprint": b"r" * 32,
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "retention_until": NOW + timedelta(minutes=15),
    }
    with migrated_engine.begin() as connection:
        connection.execute(replay.insert(), valid)

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(replay.insert(), valid | {"id": "claim-2"})

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                replay.insert(),
                valid
                | {
                    "id": "claim-3",
                    "nonce_hash": b"x" * 32,
                    "retention_until": NOW + timedelta(minutes=1),
                },
            )


def test_models_keep_application_tables_in_owned_schema() -> None:
    assert set(Base.metadata.tables) == {
        f"orchestrator.{table}" for table in EXPECTED_TABLES
    }
