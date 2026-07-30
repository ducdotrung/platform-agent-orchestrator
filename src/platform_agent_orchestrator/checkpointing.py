"""LangGraph checkpoint composition with a stable run-to-thread mapping."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import SecretStr


def thread_id_for_run(run_id: str) -> str:
    """Keep the durable run identity and LangGraph thread identity identical."""

    if not run_id or len(run_id) > 128 or run_id != run_id.strip():
        raise ValueError("run_id must contain 1 to 128 non-padded characters")
    return run_id


def checkpoint_config(run_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id_for_run(run_id)}}


@contextmanager
def postgres_checkpointer(
    database_url: SecretStr | str,
    *,
    setup: bool = False,
) -> Iterator[object]:
    """Open the supported saver without copying its credential into workflow state.

    Schema setup is opt-in so normal API and worker processes never migrate on
    startup. The migration role may call this factory with ``setup=True``.
    """

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
