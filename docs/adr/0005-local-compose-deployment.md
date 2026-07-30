# ADR-0005: Local Docker Compose Deployment

- Status: accepted for the public hackathon sample
- Date: 2026-07-30
- Decision owners: Repository Owner and Demo Operator (sample roles)
- Scope: Gate G2 deployment platform, process topology, initialization,
  configuration, health, shutdown, persistence, and local security boundary
- Depends on: ADR-0001 through ADR-0004

## Context

The public sample needs a reproducible deployment for an authenticated API,
durable event delivery, worker recovery, PostgreSQL checkpoints, approval
resume, and local side-effect receipts. It must be practical on a hackathon
workstation and explicit about the behavior that later tests need to prove.

The sample is not a company service. It has no approved cluster, registry,
identity provider, secrets manager, certificate authority, backup service,
remote MCP deployment, model gateway, alert producer, or notification system.
Choosing Kubernetes or a cloud platform now would invent requirements and hide
the local recovery semantics behind unapproved infrastructure.

ADR-0001 defines asynchronous process lifecycles. ADR-0002 removes a separate
broker and dispatcher from the first topology. ADR-0003 requires two databases
on one PostgreSQL server and separate migration ownership. ADR-0004 fixes the
sample identity and resource scope.

## Decision

Use Docker Compose v2 as the Gate G2 deployment target. The default profile is
local-only and contains one API process, one worker process, one PostgreSQL
server, explicit one-shot initialization/migration jobs, and deterministic
local adapters.

The Compose deployment demonstrates process and persistence boundaries; it is
not described as production-ready or as a template for company infrastructure.
No Kubernetes manifests, public ingress, autoscaling, cloud resources, or
remote deployment workflow are part of Gate G2.

```text
host loopback
    |
    v
+------------------- Docker Compose project --------------------+
|                                                               |
|  api -----------+                                             |
|                 |                                             |
|                 +--> platform_agent database                  |
|                 |       events / runs / jobs / audit          |
|                 |                                             |
|  worker --------+--> platform_agent_checkpoints database      |
|  (one replica)  |       LangGraph saver-owned tables          |
|       |         |                                             |
|       +---------+--> deterministic reasoner                   |
|       +------------> local receipt-only notifier              |
|                                                               |
|  one-shot jobs: database bootstrap, app migration,            |
|                 checkpoint setup, identity fixture setup      |
+---------------------------------------------------------------+

Not in the default profile:
  service-graph-toolkit live MCP, model provider, Teams/Jira,
  Sentry/company ingress, Langfuse, mutation tools
```

## Compose services

| Service | Lifecycle | Responsibility | Network/access |
| --- | --- | --- | --- |
| `postgres` | Long-running | One server hosting the two ADR-0003 databases | Private backend only; persistent named volume |
| `db-bootstrap` | One-shot | Idempotently create databases, logical roles, and grants | PostgreSQL administrative secret only |
| `app-migrate` | One-shot | Apply reviewed Alembic revisions to `platform_agent.orchestrator` | Application migrator role only |
| `checkpoint-migrate` | One-shot | Run the pinned saver `setup()` against `platform_agent_checkpoints` | Checkpoint migrator role only |
| `identity-init` | One-shot | Generate ephemeral local issuer key material into separated named volumes | No database or network access |
| `api` | Long-running | Authentication, authorization, validation, admission, query, approval, feedback, health | Loopback host port plus private backend |
| `worker` | Long-running | Claim jobs, invoke/resume graphs, heartbeat, reconcile, persist outcomes, run bounded maintenance | Private backend only |
| `demo-token` | Explicit tools profile | Issue a short-lived fixture token from the ephemeral local private key | No database access; never starts by default |
| `demo-event` | Explicit tools profile | Submit versioned synthetic Sock Shop events through the API | Loopback API access only |

The API and worker use the same immutable application image with different
entry points. Migration and maintenance commands use that image as one-shot
jobs. Runtime containers never run migrations.

There is no dispatcher service: workers claim PostgreSQL jobs directly. There
is no identity-provider service: `identity-init` and `demo-token` are local
fixtures implementing ADR-0004, not an OAuth/OIDC provider.

## Startup and migration ordering

Compose dependency conditions express these gates:

```text
postgres healthy
    |
    +--> db-bootstrap completed successfully
             |
             +--> app-migrate completed successfully ----> api
             |
             +--> checkpoint-migrate completed successfully --> worker

identity-init completed successfully ---------------------> api
```

The worker also waits for the application migration. The API does not require
the checkpoint database or a live worker for liveness or admission readiness:
an accepted event remains durable in the application queue while a worker is
temporarily unavailable. Readiness details may report worker-path degradation,
but the API fails admission readiness only when it cannot safely authenticate,
authorize, or commit the admission transaction.

One-shot jobs are idempotent. Re-running bootstrap or migrations after an
unknown Compose outcome is safe. A failed job prevents dependent runtime
services from starting. API and worker readiness independently verify expected
schema/package compatibility, so a restarted container cannot bypass an old
successful migration container.

Database bootstrap owns database/role creation only. Alembic owns application
objects. The LangGraph saver owns checkpoint objects. Bootstrap SQL must not
create either owner's tables.

## Image and dependency policy

B16 will build one multi-stage application image with:

- a pinned Python 3.12 patch-level base image;
- a locked application dependency set generated from `pyproject.toml`;
- no compiler, package manager cache, test dependency, or source-control
  credential in the runtime stage;
- a non-root runtime user and explicit entry point;
- an OCI source/revision label.

The sample uses PostgreSQL major version 17. B16 pins the exact image digest
and records the patch update procedure. Application, PostgreSQL, and migration
images are never referenced by a floating `latest` tag.

Build inputs come only from this repository for Gate G2. No sibling repository,
private package index, source corpus, model credential, or company artifact is
copied into the default image. A future service-graph adapter packaging decision
is defined separately in ADR-0006.

## Configuration and secrets

Configuration is validated once at process startup and split into:

- public immutable settings: environment `demo`, resource scope
  `sock-shop-sample`, policy/contract versions, limits, and adapter selection;
- secret file paths: database passwords and any future private credentials;
- ephemeral local identity volumes: private signing key visible only to
  `demo-token`, public verification key visible only to `api`.

A repository command created in B16 must generate random local database secrets
into an ignored, owner-readable directory before `docker compose up`.
Top-level Compose secrets mount those files only into services that require
them. Compose secrets are a local file-delivery mechanism, not an encrypted
company secrets manager.

The repository contains example names and setup instructions, never usable
secret values. Secrets are not placed in image layers, Compose command
arguments, environment dumps, URLs, graph state, events, audit rows, logs, or
traces. The API never receives the local fixture private key. The worker
receives no authentication signing material.

Missing, default-looking, world-readable, or malformed secrets fail setup or
readiness. There is no fallback credential or authentication-disabled profile.

## Network boundary

The default deployment uses:

- an ingress bridge where only `api` is published as
  `127.0.0.1:<configured-port>`;
- a private internal backend network shared by API, worker, migrations, and
  PostgreSQL;
- no host PostgreSQL port;
- no host Docker socket;
- no public listener and no untrusted forwarded-header mode.

The worker has no external adapter in Gate G2, so it requires no internet
egress for runtime behavior. Image build/download is a separate operator
action. Enabling any live adapter changes the egress and threat boundary and
requires ADR-0006 plus the A08 threat-model gate.

Local loopback HTTP is the only TLS exception allowed by ADR-0004. Binding the
API to a non-loopback address requires a new deployment decision with TLS,
trusted proxy, issuer, rate-limit, and abuse-control ownership.

## Container hardening

Application runtime services:

- run as a numeric non-root user;
- set a read-only root filesystem;
- use explicit writable `tmpfs` mounts only where required;
- drop Linux capabilities and set `no-new-privileges`;
- have bounded CPU/memory/concurrency settings documented by B16;
- never run privileged or mount the Docker socket;
- receive only their minimum database and secret files;
- use exec-form commands so API/worker processes receive signals directly.

PostgreSQL and one-shot jobs receive only the exceptions required for their
owned volume or task. Those exceptions are service-specific rather than copied
to every container.

## Health and readiness

Health is deterministic and does not call a model or an LLM.

| Check | Meaning | Dependencies |
| --- | --- | --- |
| API `/health/live` | Event loop/process can respond | None |
| API `/health/ready` | Admission can durably accept authorized work | App DB reachable, expected schema, policy/auth key loaded |
| Worker health command | Process can claim and heartbeat work | App DB, expected schema, checkpoint DB/saver, policy and enabled adapters |
| PostgreSQL health | Server accepts a local SQL connection | PostgreSQL only |

Readiness returns bounded component states without credentials, DSNs, SQL,
internal hostnames, or stack traces. Optional telemetry never affects
readiness. A live process may correctly be unready during migration, database
failure, stale policy, or adapter incompatibility.

Compose health checks call local endpoints/commands and use
`service_healthy` only for real readiness dependencies. Fixed sleeps are not
startup synchronization.

## Shutdown and recovery

Compose sends `SIGTERM`. The API:

1. becomes unready;
2. stops accepting new admissions;
3. drains bounded in-flight request transactions;
4. closes pools/clients;
5. exits within a 15-second grace period.

The worker:

1. becomes unready and stops claiming jobs;
2. continues heartbeats while bounded in-flight work drains;
3. cancels graph/adapter work that cannot complete safely;
4. does not start another external side effect;
5. records or releases a lease only with the current fence;
6. closes checkpointer, adapter, and database resources;
7. exits within a 45-second grace period.

If forced termination wins, ADR-0002 lease expiry and ADR-0003 reconciliation
recover the job. Shutdown never waits indefinitely and never marks uncommitted
work successful.

Runtime services use `restart: unless-stopped` only after initialization
succeeds. One-shot jobs do not restart forever. Repeated crash loops remain
visible as unhealthy/failed rather than being hidden by an unbounded script.

## Data lifecycle

Named volumes persist PostgreSQL data across normal Compose restart and
`docker compose down`. Removing volumes is an explicit destructive operator
action and is never part of normal teardown or tests that point at a developer
environment.

The A05 retention worker operates inside the application boundary. The local
sample has no automated backup/PITR and makes no durability claim after host or
volume loss. Company deployment must decide backup, restore, encryption,
regional recovery, and deletion behavior together.

Ephemeral identity keys may be deliberately rotated by replacing their named
volumes; this invalidates sample tokens. Database secrets require an explicit
rotation command and connection restart.

## Profiles and feature gates

| Profile | Contents | Default? |
| --- | --- | --- |
| Core | PostgreSQL, bootstrap/migrations, identity fixture, API, worker | Yes |
| Tools | `demo-token`, `demo-event`, migration/status commands | No; invoked explicitly |
| Observability | Local Prometheus-compatible scrape/debug tooling when B15 exists | No |
| Live knowledge | Not defined until ADR-0006 packaging precondition is met | No |

Adapter selection is allow-listed configuration. An unknown adapter or a
network adapter without its required contract/version fails startup. The API
exposes only the alert-review workflow in this deployment. Knowledge refresh,
engineering assistance, SRE actions, publication, and auto-send are not
deployable feature flags.

## Release, promotion, and rollback

B16 must record immutable application image digest, source revision,
application/checkpoint migration versions, policy version, and dependency
lock digest.

The local update flow is:

1. build and scan the candidate image;
2. run unit, migration, integration, signal, and recovery tests;
3. back up disposable demo evidence if the operator wants it;
4. run forward migrations;
5. start API/worker only after readiness gates;
6. execute an authenticated synthetic smoke event;
7. record the release identity.

Rollback normally restores the previous application image while leaving
forward-compatible schema in place. Destructive database downgrade and
automatic volume deletion are not rollback strategies. A migration that
prevents the prior image from running requires an explicit restore/recovery
exercise before release.

## Alternatives considered

### Run every component directly on the host

Rejected as the Gate G2 target. It is useful during development but does not
prove image, signal, network, secret-mount, migration-job, or dependency-start
behavior.

### Kubernetes

Deferred. It would require unapproved ingress, secret, migration, storage,
health, identity, and operational ownership. Compose is sufficient for the
single-workstation public sample.

### Add Redis, RabbitMQ, Kafka, or a dispatcher

Rejected by ADR-0002 for the first slice. PostgreSQL is the durable queue.

### Put API and worker in one process

Rejected. Independent failure, scaling, readiness, and shutdown boundaries are
required even with one replica each.

### Include every future adapter in the default image

Rejected. It expands supply-chain, credential, egress, and mutation surface
before the contracts and threat model are approved.

## Consequences

### Benefits

- Gate G2 has one reproducible and inspectable deployment target.
- Migration ownership and startup dependencies are executable concepts.
- API and worker crash/recovery behavior stays visible.
- Default runtime needs no external credentials or network side effects.
- Company deployment assumptions are not smuggled into the public sample.

### Costs and limits

- Compose is single-host and does not prove cluster scheduling or failover.
- Local secret files and named volumes are not a company control plane.
- One PostgreSQL server remains a single failure domain.
- The default image cannot run the live service-graph MCP adapter.
- Exact lockfiles, Dockerfiles, Compose files, and CI arrive in B03/B16.

## Verification required by B16

- Fresh setup creates secret files with restrictive permissions and no tracked
  values.
- Images build reproducibly from locked inputs and run as non-root.
- PostgreSQL health, bootstrap, both migration jobs, API, and worker start in
  the required order without fixed sleeps.
- A second bootstrap/migration run is a no-op or safe success.
- API is loopback-only; PostgreSQL is not published; runtime has no Docker
  socket or unneeded secret.
- Liveness remains available during dependency failure while readiness fails.
- `SIGTERM` stops new work, drains/cancels safely, and exits within the
  configured grace period.
- Worker kill/restart reclaims an expired lease and resumes the same thread.
- Duplicate delivery produces one durable local receipt.
- Normal teardown preserves volumes; destructive teardown is explicit.
- No default profile contacts an external model, MCP, alert, notification, or
  telemetry service.

## References

- [Docker Compose startup and shutdown order](https://docs.docker.com/compose/how-tos/startup-order/)
- [Docker Compose service reference](https://docs.docker.com/reference/compose-file/services/)
- [ADR-0001: Async runtime and lifecycle](0001-async-runtime-and-lifecycle.md)
- [ADR-0002: PostgreSQL durable delivery](0002-postgres-durable-delivery.md)
- [ADR-0003: Persistence, checkpoints, and retention](0003-persistence-checkpoints-and-retention.md)
- [ADR-0004: Authentication, authorization, and replay](0004-authentication-authorization-and-replay.md)
- [ADR-0006: External adapter contracts](0006-external-adapter-contracts.md)
