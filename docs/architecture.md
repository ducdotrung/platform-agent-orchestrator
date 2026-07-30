# Architecture and migration guide

## Ownership

| Capability | Owner |
|---|---|
| Workflow state, routing, approvals | this repository |
| Code/service graph extraction | `service-graph-toolkit` |
| Alert source plugins and policy | `sre-alert-agent` |
| Infrastructure knowledge and commands | `sre-skills` |
| Wiki, browsing, and user chat UI | `code-atlas-workbench` |

The orchestrator references those systems through typed ports. It must not
silently become a second implementation of them.

## Shared contracts

- `DomainEvent`: immutable trigger with an idempotency key and correlation ID.
- `EvidenceRef`: bounded reference to a revision, path, URL, or graph locator.
- `KnowledgeArtifact`: revisioned output with provenance and confidence.
- `AgentDecision`: structured recommendation, never an untyped prose blob.
- `ActionRequest` / `ActionResult`: auditable mutation boundary.

Workflow checkpoints and knowledge snapshots are different stores. A
checkpoint answers “where is this execution?” A knowledge snapshot answers
“what was believed at revision X, and why?”

## Production topology

The service runtime and I/O lifecycle follow
[ADR-0001](adr/0001-async-runtime-and-lifecycle.md): API, worker, any future
dispatcher, graph invocation, and I/O-bearing ports are async; deterministic
CPU-light nodes remain synchronous.

For the public sample, [ADR-0002](adr/0002-postgres-durable-delivery.md)
implements the admission outbox as a PostgreSQL durable job queue consumed
directly by workers. There is no separate broker or dispatcher. Delivery is at
least once; checkpoints and durable side-effect receipts remain separate.

[ADR-0003](adr/0003-persistence-checkpoints-and-retention.md) places
application records and LangGraph checkpoints in separate databases on the same
sample PostgreSQL server. Application code never queries saver-managed tables,
and telemetry remains outside both authoritative stores.

```text
webhook receivers / schedules
          |
          v
 event validation + outbox
          |
          v
 LangGraph workers ---- Postgres checkpointer
          |
          +---- read-only knowledge MCP/API
          +---- allow-listed action API
          +---- snapshot publisher
          +---- Teams/Jira notification API
          +---- Langfuse telemetry (optional)
```

Use a durable job/outbox between webhook receipt and workflow invocation. A
checkpointer is not a replacement for delivery state. A broker is a future
scaling option, not a requirement for the public sample.

Langfuse receives traces and evaluation scores through an optional backend. It
does not replace checkpoints, the event outbox, action audit logs, or knowledge
snapshots. Telemetry failure must not change workflow policy or business state.

## Migration sequence

1. Run the alert graph with deterministic demo ports.
2. Replace only the knowledge and notification ports with real adapters.
3. Dual-write the current alert files and graph checkpoints until replay and
   audit behavior are verified.
4. Add Bitbucket merged-PR events and a real knowledge publisher.
5. Add Code Atlas query routing.
6. Add SRE action execution last, after authorization and approval auditing are
   independently tested.

## Safety

- Webhook payloads are untrusted data, not instructions.
- Retrieval tools are read-only by default.
- Mutation tools are separately deployed and allow-listed.
- Human approval includes actor, reason, timestamp, and requested action hash.
- Publication is atomic: readers see either the old snapshot or the fully
  validated new snapshot.
