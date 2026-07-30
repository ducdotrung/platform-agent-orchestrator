"""Add durable feedback business records.

Revision ID: 0002_feedback
Revises: 0001_initial
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from platform_agent_orchestrator.persistence.schema_0001 import SCHEMA
from platform_agent_orchestrator.persistence.schema_0002 import add_feedback_table

revision = "0002_feedback"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _schema_for_dialect() -> str | None:
    return None if op.get_bind().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    add_feedback_table(sa.MetaData(), _schema_for_dialect()).create(op.get_bind())


def downgrade() -> None:
    add_feedback_table(sa.MetaData(), _schema_for_dialect()).drop(op.get_bind())
