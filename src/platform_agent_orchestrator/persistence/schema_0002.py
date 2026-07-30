"""Frozen feedback schema introduced by migration 0002."""

from __future__ import annotations

import sqlalchemy as sa

from .schema_0001 import SCHEMA, _qualified


def add_feedback_table(
    metadata: sa.MetaData,
    schema: str | None = SCHEMA,
) -> sa.Table:
    timestamp = sa.DateTime(timezone=True)
    run_table_key = f"{schema}.runs" if schema else "runs"
    if run_table_key not in metadata.tables:
        sa.Table(
            "runs",
            metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            schema=schema,
        )
    return sa.Table(
        "feedback",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey(_qualified(schema, "runs")),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("rating", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("trace_id", sa.String(128)),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("retention_until", timestamp, nullable=False),
        sa.Column("metadata", sa.JSON, key="metadata_json", nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.CheckConstraint(
            "rating IN ('helpful', 'not_helpful', 'unsafe')", name="rating_valid"
        ),
        sa.CheckConstraint("length(reason) <= 2048", name="reason_bounded"),
        sa.CheckConstraint(
            "length(CAST(metadata AS TEXT)) <= 8192", name="metadata_bounded"
        ),
        sa.CheckConstraint(
            "retention_until >= created_at", name="retention_after_creation"
        ),
        sa.CheckConstraint("version >= 0", name="version_nonnegative"),
        schema=schema,
    )
