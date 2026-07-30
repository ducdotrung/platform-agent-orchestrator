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

The repository test suite executes upgrade/downgrade and portable constraints
with SQLite and compiles schema-qualified PostgreSQL DDL offline. This does not
claim PostgreSQL integration coverage. Gate G2 additionally requires the B16
Compose migration smoke test against the pinned PostgreSQL image.
