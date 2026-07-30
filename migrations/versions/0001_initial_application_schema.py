"""Create the initial orchestration application schema.

Revision ID: 0001_initial
Revises: None
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.schema import CreateSchema, DropSchema

from platform_agent_orchestrator.persistence.schema_0001 import SCHEMA, build_metadata

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _schema_for_dialect() -> str | None:
    return None if op.get_bind().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    schema = _schema_for_dialect()
    if schema is not None:
        op.execute(CreateSchema(schema, if_not_exists=True))
    build_metadata(schema).create_all(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    schema = _schema_for_dialect()
    build_metadata(schema).drop_all(op.get_bind(), checkfirst=False)
    if schema is not None:
        op.execute(DropSchema(schema, cascade=True, if_exists=True))
