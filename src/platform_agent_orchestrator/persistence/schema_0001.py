"""Frozen table definitions used by application models and revision 0001."""

from __future__ import annotations

import sqlalchemy as sa

SCHEMA = "orchestrator"

RUN_STATES = (
    "queued",
    "running",
    "waiting_approval",
    "retry_wait",
    "succeeded",
    "rejected",
    "failed_terminal",
    "dead_lettered",
    "quarantined",
)
JOB_STATES = (
    "pending",
    "leased",
    "retry_wait",
    "completed",
    "failed_terminal",
    "dead_lettered",
    "quarantined",
)
ERROR_CATEGORIES = (
    "retryable_transient",
    "worker_lost",
    "terminal_input",
    "terminal_dependency",
    "terminal_policy",
    "ambiguous_side_effect",
    "poison_or_security",
)


def _qualified(schema: str | None, table: str, column: str = "id") -> str:
    prefix = f"{schema}." if schema else ""
    return f"{prefix}{table}.{column}"


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def build_metadata(schema: str | None = SCHEMA) -> sa.MetaData:
    metadata = sa.MetaData(
        schema=schema,
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )
    timestamp = sa.DateTime(timezone=True)

    sa.Table(
        "events",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("occurred_at", timestamp, nullable=False),
        sa.Column("received_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column("fingerprint", sa.LargeBinary(32), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("payload_purged_at", timestamp),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "scope_id", "source", "idempotency_key", name="event_identity"
        ),
        sa.CheckConstraint("length(fingerprint) = 32", name="fingerprint_32_bytes"),
        sa.CheckConstraint(
            "length(CAST(payload AS TEXT)) <= 65536", name="payload_at_most_64k"
        ),
        sa.CheckConstraint("version >= 0", name="version_nonnegative"),
    )

    terminal_runs = (
        "succeeded",
        "rejected",
        "failed_terminal",
        "dead_lettered",
        "quarantined",
    )
    runs = sa.Table(
        "runs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey(_qualified(schema, "events")),
            nullable=False,
        ),
        sa.Column("workflow", sa.String(64), nullable=False),
        sa.Column("workflow_contract_version", sa.String(32), nullable=False),
        sa.Column(
            "replay_of_run_id",
            sa.String(36),
            sa.ForeignKey(_qualified(schema, "runs")),
        ),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_summary", sa.Text),
        sa.Column("error_category", sa.String(64)),
        sa.Column("error_fingerprint", sa.LargeBinary(32)),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", timestamp),
        sa.Column("interrupted_at", timestamp),
        sa.Column("finished_at", timestamp),
        sa.Column("release_id", sa.String(128)),
        sa.Column("checkpoint_deleted_at", timestamp),
        sa.Column("operator_closed_at", timestamp),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("scope_id", "thread_id", name="run_thread"),
        sa.CheckConstraint(f"status IN ({_values(RUN_STATES)})", name="status_valid"),
        sa.CheckConstraint("thread_id = id", name="thread_matches_run"),
        sa.CheckConstraint(
            "result_summary IS NULL OR length(result_summary) <= 16384",
            name="result_summary_bounded",
        ),
        sa.CheckConstraint(
            "error_fingerprint IS NULL OR length(error_fingerprint) = 32",
            name="error_fingerprint_32_bytes",
        ),
        sa.CheckConstraint(
            f"error_category IS NULL OR error_category IN ({_values(ERROR_CATEGORIES)})",
            name="error_category_valid",
        ),
        sa.CheckConstraint(
            f"((status IN ({_values(terminal_runs)}) AND finished_at IS NOT NULL) OR "
            f"(status NOT IN ({_values(terminal_runs)}) AND finished_at IS NULL))",
            name="terminal_timestamp_consistent",
        ),
        sa.CheckConstraint(
            "status != 'waiting_approval' OR interrupted_at IS NOT NULL",
            name="approval_interrupt_present",
        ),
        sa.CheckConstraint("version >= 0", name="version_nonnegative"),
    )
    sa.Index(
        "uq_runs_initial_event",
        runs.c.event_id,
        unique=True,
        postgresql_where=runs.c.replay_of_run_id.is_(None),
        sqlite_where=runs.c.replay_of_run_id.is_(None),
    )

    jobs = sa.Table(
        "delivery_jobs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey(_qualified(schema, "runs")),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("operation_key", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("available_at", timestamp, nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
        sa.Column("lease_token", sa.String(256)),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", timestamp),
        sa.Column("last_heartbeat_at", timestamp),
        sa.Column("last_error_category", sa.String(64)),
        sa.Column("last_error_fingerprint", sa.LargeBinary(32)),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", timestamp),
        sa.Column("operator_closed_at", timestamp),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "scope_id", "run_id", "kind", "operation_key", name="job_operation"
        ),
        sa.CheckConstraint("kind IN ('invoke', 'resume')", name="kind_valid"),
        sa.CheckConstraint(f"status IN ({_values(JOB_STATES)})", name="status_valid"),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts AND max_attempts > 0",
            name="attempt_budget_valid",
        ),
        sa.CheckConstraint(
            "((status = 'leased' AND lease_token IS NOT NULL AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR (status != 'leased' AND lease_token IS NULL "
            "AND lease_owner IS NULL AND lease_expires_at IS NULL))",
            name="lease_fields_consistent",
        ),
        sa.CheckConstraint(
            "last_error_fingerprint IS NULL OR length(last_error_fingerprint) = 32",
            name="error_fingerprint_32_bytes",
        ),
        sa.CheckConstraint(
            "last_error_category IS NULL OR "
            f"last_error_category IN ({_values(ERROR_CATEGORIES)})",
            name="error_category_valid",
        ),
        sa.CheckConstraint("version >= 0", name="version_nonnegative"),
    )
    sa.Index(
        "ix_delivery_jobs_available",
        jobs.c.available_at,
        jobs.c.created_at,
        jobs.c.id,
        postgresql_where=jobs.c.status.in_(("pending", "retry_wait")),
        sqlite_where=jobs.c.status.in_(("pending", "retry_wait")),
    )
    sa.Index(
        "ix_delivery_jobs_expired_lease",
        jobs.c.lease_expires_at,
        jobs.c.id,
        postgresql_where=jobs.c.status == "leased",
        sqlite_where=jobs.c.status == "leased",
    )

    attempts = sa.Table(
        "delivery_attempts",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey(_qualified(schema, "delivery_jobs")),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column("lease_token", sa.String(256), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("started_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("last_heartbeat_at", timestamp),
        sa.Column("finished_at", timestamp),
        sa.Column("outcome", sa.String(64)),
        sa.Column("error_category", sa.String(64)),
        sa.Column("error_fingerprint", sa.LargeBinary(32)),
        sa.Column("retry_available_at", timestamp),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("job_id", "attempt_number", name="attempt_number"),
        sa.UniqueConstraint("job_id", "lease_token", name="attempt_lease"),
        sa.CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        sa.CheckConstraint(
            "error_fingerprint IS NULL OR length(error_fingerprint) = 32",
            name="error_fingerprint_32_bytes",
        ),
        sa.CheckConstraint(
            f"error_category IS NULL OR error_category IN ({_values(ERROR_CATEGORIES)})",
            name="error_category_valid",
        ),
        sa.CheckConstraint("version >= 0", name="version_nonnegative"),
    )
    sa.Index(
        "uq_delivery_attempts_active_job",
        attempts.c.job_id,
        unique=True,
        postgresql_where=attempts.c.finished_at.is_(None),
        sqlite_where=attempts.c.finished_at.is_(None),
    )

    sa.Table(
        "idempotency_claims",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("boundary", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.LargeBinary(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("resource_kind", sa.String(64)),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("response_status", sa.Integer),
        sa.Column("response_summary", sa.Text),
        sa.Column("created_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", timestamp),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "scope_id", "boundary", "idempotency_key", name="idempotency_identity"
        ),
        sa.CheckConstraint(
            "boundary IN ('admission', 'approval', 'operator_replay')",
            name="boundary_valid",
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'succeeded', 'failed_terminal')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 32", name="fingerprint_32_bytes"
        ),
        sa.CheckConstraint(
            "response_summary IS NULL OR length(response_summary) <= 8192",
            name="response_summary_bounded",
        ),
        sa.CheckConstraint("expires_at >= created_at", name="retention_after_creation"),
        sa.CheckConstraint("version >= 0", name="version_nonnegative"),
    )

    sa.Table(
        "auth_replay_claims",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("authenticator_id", sa.String(128), nullable=False),
        sa.Column("nonce_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("request_fingerprint", sa.LargeBinary(32), nullable=False),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column("retention_until", timestamp, nullable=False),
        sa.UniqueConstraint("authenticator_id", "nonce_hash", name="auth_nonce"),
        sa.CheckConstraint("length(nonce_hash) = 32", name="nonce_hash_32_bytes"),
        sa.CheckConstraint(
            "length(request_fingerprint) = 32", name="fingerprint_32_bytes"
        ),
        sa.CheckConstraint("expires_at >= created_at", name="expiry_after_creation"),
        sa.CheckConstraint(
            "retention_until >= expires_at", name="retention_after_expiry"
        ),
    )

    sa.Table(
        "approvals",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey(_qualified(schema, "runs")),
            nullable=False,
        ),
        sa.Column("approval_version", sa.Integer, nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("action_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("decided_at", timestamp, nullable=False),
        sa.Column("expires_at", timestamp, nullable=False),
        sa.Column(
            "idempotency_claim_id",
            sa.String(36),
            sa.ForeignKey(_qualified(schema, "idempotency_claims")),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("run_id", "approval_version", name="run_approval_version"),
        sa.CheckConstraint("approval_version > 0", name="approval_version_positive"),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="decision_valid"),
        sa.CheckConstraint("actor_type IN ('reviewer', 'operator')", name="actor_valid"),
        sa.CheckConstraint("length(reason) <= 2048", name="reason_bounded"),
        sa.CheckConstraint("length(action_hash) = 32", name="action_hash_32_bytes"),
        sa.CheckConstraint("expires_at >= decided_at", name="expiry_after_decision"),
        sa.CheckConstraint("version >= 0", name="version_nonnegative"),
    )

    sa.Table(
        "side_effects",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey(_qualified(schema, "runs")),
            nullable=False,
        ),
        sa.Column("effect_kind", sa.String(64), nullable=False),
        sa.Column("destination", sa.String(256), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(512), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("claim_token", sa.String(256)),
        sa.Column("claim_expires_at", timestamp),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("receipt", sa.JSON),
        sa.Column("provider_reference", sa.String(256)),
        sa.Column("available_at", timestamp),
        sa.Column("reserved_at", timestamp, nullable=False),
        sa.Column("started_at", timestamp),
        sa.Column("completed_at", timestamp),
        sa.Column("reconciled_at", timestamp),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "scope_id", "effect_kind", "idempotency_key", name="effect_identity"
        ),
        sa.CheckConstraint("length(request_hash) = 32", name="request_hash_32_bytes"),
        sa.CheckConstraint(
            "status IN ('reserved', 'in_progress', 'retry_wait', 'succeeded', "
            "'failed_terminal', 'unknown')",
            name="status_valid",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        sa.CheckConstraint(
            "receipt IS NULL OR length(CAST(receipt AS TEXT)) <= 16384",
            name="receipt_bounded",
        ),
        sa.CheckConstraint(
            "receipt IS NULL OR status = 'succeeded'", name="receipt_only_on_success"
        ),
        sa.CheckConstraint("version >= 0", name="version_nonnegative"),
    )

    audit_id_type = sa.BigInteger().with_variant(sa.Integer, "sqlite")
    sa.Table(
        "audit_events",
        metadata,
        sa.Column("id", audit_id_type, primary_key=True, autoincrement=True),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("occurred_at", timestamp, nullable=False, server_default=sa.func.now()),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("event_id", sa.String(36)),
        sa.Column("run_id", sa.String(36)),
        sa.Column("job_id", sa.String(36)),
        sa.Column("approval_id", sa.String(36)),
        sa.Column("side_effect_id", sa.String(36)),
        sa.Column("request_id", sa.String(128)),
        sa.Column("correlation_id", sa.String(128)),
        sa.Column("prior_state", sa.String(64)),
        sa.Column("new_state", sa.String(64)),
        sa.Column("action_hash", sa.LargeBinary(32)),
        sa.Column("metadata", sa.JSON, key="metadata_json", nullable=False),
        sa.CheckConstraint(
            "action_hash IS NULL OR length(action_hash) = 32",
            name="action_hash_32_bytes",
        ),
        sa.CheckConstraint(
            "length(CAST(metadata AS TEXT)) <= 8192", name="metadata_bounded"
        ),
    )

    return metadata
