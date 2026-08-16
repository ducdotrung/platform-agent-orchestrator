"""LangGraph checkpoint composition isolated from framework contracts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr


def thread_id_for_run(run_id: str) -> str:
    """Validate the stable identifier used for one checkpoint thread."""

    if not run_id or len(run_id) > 128 or run_id != run_id.strip():
        raise ValueError("run_id must contain 1 to 128 non-padded characters")
    return run_id


def checkpoint_config(run_id: str) -> dict[str, dict[str, str]]:
    """Build the implementation-owned invocation configuration."""

    return {"configurable": {"thread_id": thread_id_for_run(run_id)}}


@dataclass(frozen=True)
class LangGraphCheckpoint:
    """Own a saver while keeping it out of flow and checkpoint state."""

    saver: object = field(default_factory=InMemorySaver)

    def config(self, thread_id: str) -> dict[str, dict[str, str]]:
        return checkpoint_config(thread_id)


@contextmanager
def postgres_checkpointer(
    database_url: SecretStr | str,
    *,
    setup: bool = False,
) -> Iterator[object]:
    """Open the supported Postgres saver without copying credentials into state."""

    from langgraph.checkpoint.postgres import PostgresSaver

    raw_url = (
        database_url.get_secret_value()
        if isinstance(database_url, SecretStr)
        else database_url
    )
    connection_url = _psycopg_connection_url(raw_url)
    with PostgresSaver.from_conn_string(connection_url) as checkpointer:
        if setup:
            checkpointer.setup()
        yield checkpointer


def _psycopg_connection_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    if database_url.startswith("postgresql://"):
        return database_url
    raise ValueError("checkpoint database URL must use PostgreSQL")
