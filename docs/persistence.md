# Application persistence

The application tables are owned by Alembic under the PostgreSQL
`orchestrator` schema. LangGraph checkpoint tables remain separately owned and
are never created or inspected by these migrations.

Run migrations with a dedicated migration identity:

```bash
ORCHESTRATOR_DATABASE_URL='postgresql+psycopg://...' \
  .venv/bin/alembic upgrade head
```

API and worker startup must only check the current revision; they do not run
DDL. The initial revision defines bounded payloads and summaries, scoped
idempotency, fenced delivery leases, immutable replay identities, approval
expiry, side-effect receipts, and append-only audit records.

The default repository test suite executes upgrade/downgrade and portable
constraints with SQLite and compiles schema-qualified PostgreSQL DDL offline.
Setting `TEST_POSTGRES_URL` and `TEST_CHECKPOINT_POSTGRES_URL` enables real
PostgreSQL integration coverage for parent/child admission ordering,
checkpointed workflow execution, durable notification, approval/resume, and
terminal run persistence. This passed against a temporary PostgreSQL 16.14
process on 2026-07-30. Gate G2 additionally requires the B16 image build and
Compose migration smoke test against the pinned PostgreSQL image.

`EventRepository` commits event, initial run, pending delivery job, and audit
record in one transaction. Its claim path uses ordered `FOR UPDATE SKIP LOCKED`
on PostgreSQL, closes an expired active attempt as `worker_lost`, and creates a
new lease token and attempt. The SQLite test shim serializes claims only because
SQLite does not implement this PostgreSQL lock behavior.

`DatabaseJobDispatcher` is the selected B09 dispatcher. It does not publish a
second copy of a job: it retries bounded transient claim failures against the
authoritative table, validates claimed records, and wakes retries on shutdown.
