"""Run reviewed Alembic migrations using secret-file runtime settings."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from platform_agent_orchestrator.runtime.process import _runtime_settings


def main() -> None:
    settings = _runtime_settings()
    assert settings.database_url is not None
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    config.set_main_option(
        "sqlalchemy.url",
        settings.database_url.get_secret_value().replace("%", "%%"),
    )
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
