"""Idempotently create the saver-owned checkpoint database."""

from __future__ import annotations

import psycopg
from psycopg import sql

from platform_agent_orchestrator.runtime import _runtime_settings


def main() -> None:
    settings = _runtime_settings()
    assert settings.database_url is not None
    database_name = "platform_agent_checkpoints"
    connection_url = settings.database_url.get_secret_value().replace(
        "postgresql+psycopg://", "postgresql://"
    )
    with psycopg.connect(connection_url, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
        ).fetchone()
        if exists is None:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )


if __name__ == "__main__":
    main()
