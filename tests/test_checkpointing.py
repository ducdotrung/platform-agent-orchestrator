from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import SecretStr

from platform_agent_orchestrator.adapters import DemoPlatformServices
from platform_agent_orchestrator.checkpointing import (
    _psycopg_connection_url,
    checkpoint_config,
    postgres_checkpointer,
    thread_id_for_run,
)
from platform_agent_orchestrator.contracts import DomainEvent, EventType
from platform_agent_orchestrator.registry import WorkflowRegistry


def risky_ticket() -> DomainEvent:
    return DomainEvent(
        type=EventType.SRE_TICKET_UPDATED,
        source="sample-ticket-system",
        subject="INF-2",
        idempotency_key="sample:ticket:INF-2",
        payload={
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
    checkpoint_path = tmp_path / "checkpoints.db"
    run_id = "run-INF-2"
    event = risky_ticket()
    first_demo = DemoPlatformServices()

    first_connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        first_registry = WorkflowRegistry(
            first_demo.as_services(),
            checkpointer=SqliteSaver(first_connection),
        )
        paused = first_registry.invoke("sre", event, thread_id=run_id)
        assert "__interrupt__" in paused
        assert not first_demo.actions.results
    finally:
        first_connection.close()

    second_demo = DemoPlatformServices()
    second_connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        graph = WorkflowRegistry(
            second_demo.as_services(),
            checkpointer=SqliteSaver(second_connection),
        ).build("sre")
        resumed = graph.invoke(
            Command(
                resume={
                    "approved": True,
                    "actor": "sample-reviewer",
                    "reason": "Hackathon restart-resume test",
                }
            ),
            config=checkpoint_config(run_id),
        )
    finally:
        second_connection.close()

    assert resumed["status"] == "completed"
    assert resumed["approval"]["actor"] == "sample-reviewer"
    assert len(second_demo.actions.results) == 1
