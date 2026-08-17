from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import SecretStr

from platform_agent_orchestrator.adapters import DemoAdapters
from platform_agent_orchestrator.bootstrap import build_dependencies
from platform_agent_orchestrator.checkpointing import (
    _psycopg_connection_url,
    checkpoint_config,
    postgres_checkpointer,
    thread_id_for_run,
)
from platform_agent_orchestrator.core import DomainEvent
from platform_agent_orchestrator.runtime import RunMetadata, RunStatus


def risky_ticket() -> DomainEvent:
    return DomainEvent(
        id="sre-restart-event",
        type="sre.ticket.updated",
        source="sample-ticket-system",
        subject="INF-2",
        occurred_at=datetime(2026, 8, 17, tzinfo=UTC),
        correlation_id="sre-restart-correlation",
        idempotency_key="sample:ticket:INF-2",
        tenant_id="tenant-1",
        data={
            "key": "INF-2",
            "summary": "Restart production service",
            "service": "payment",
            "environment": "prod",
            "operation": "restart",
        },
    )


def test_thread_id_mapping_is_stable_and_bounded() -> None:
    assert thread_id_for_run("run-123") == "run-123"
    assert checkpoint_config("run-123") == {"configurable": {"thread_id": "run-123"}}
    for invalid in ("", " padded", "padded ", "x" * 129):
        with pytest.raises(ValueError):
            thread_id_for_run(invalid)


def test_postgres_factory_normalizes_sqlalchemy_driver_url(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool]] = []

    class FakeSaver:
        def setup(self) -> None:
            calls.append(("setup", True))

    class FakeContext:
        def __enter__(self) -> FakeSaver:
            return FakeSaver()

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_from_conn_string(url: str) -> FakeContext:
        calls.append((url, False))
        return FakeContext()

    monkeypatch.setattr(
        "langgraph.checkpoint.postgres.PostgresSaver.from_conn_string",
        fake_from_conn_string,
    )
    secret = SecretStr("postgresql+psycopg://user:password@db/orchestrator")
    with postgres_checkpointer(secret, setup=True):
        pass

    assert calls == [
        ("postgresql://user:password@db/orchestrator", False),
        ("setup", True),
    ]
    assert "password" not in repr(secret)
    with pytest.raises(ValueError):
        _psycopg_connection_url("sqlite:///checkpoint.db")


def test_process_restart_resumes_same_interrupted_thread(tmp_path: Path) -> None:
    async def exercise_restart() -> tuple[object, DemoAdapters]:
        checkpoint_path = tmp_path / "checkpoints.db"
        event = risky_ticket()
        first_demo = DemoAdapters()
        first_dependencies = build_dependencies(demo=first_demo)
        try:
            async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                paused = (
                    await first_dependencies.dispatcher(checkpointer=saver).dispatch(event)
                )[0]
            assert paused.status is RunStatus.PAUSED
            assert paused.pause is not None
            assert paused.pause.approval is not None
            assert not first_demo.actions.results
        finally:
            first_dependencies.shutdown()

        run = RunMetadata(
            run_id=paused.run_id,
            flow_name="sre",
            flow_version=first_dependencies.flows.get("sre").metadata.version,
            thread_id=paused.run_id,
            correlation_id=event.correlation_id,
            tenant_id=event.tenant_id,
            status=RunStatus.PAUSED.value,
        )
        second_demo = DemoAdapters()
        second_dependencies = build_dependencies(demo=second_demo)
        try:
            async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                resumed = await second_dependencies.dispatcher(checkpointer=saver).resume(
                    run,
                    {
                        "approved": True,
                        "actor": "sample-reviewer",
                        "reason": "Hackathon restart-resume test",
                    },
                )
        finally:
            second_dependencies.shutdown()
        return resumed, second_demo

    resumed, second_demo = asyncio.run(exercise_restart())

    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.output["status"] == "completed"
    assert resumed.output["approval"]["actor"] == "sample-reviewer"
    assert len(second_demo.actions.results) == 1
