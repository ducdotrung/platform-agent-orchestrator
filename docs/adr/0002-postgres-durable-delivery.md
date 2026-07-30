# ADR-0002: PostgreSQL Durable Delivery Without a Broker

- Status: accepted for the public hackathon sample
- Date: 2026-07-30
- Decision owners: Repository Owner and Repository Maintainer (sample roles)
- Scope: event admission, durable workflow delivery, retries, recovery, and
  approval resume
- Amends: ADR-0001 runtime-boundary item 3; the initial topology has no separate
  dispatcher process

## Context

The API must acknowledge an event only after it can survive process failure.
Workflow execution must be asynchronous, at least once, recoverable after a
worker dies, and safe under duplicate client requests and duplicate worker
delivery.

The public hackathon sample runs locally and does not need the operational cost
of Kafka, RabbitMQ, SQS, or another broker. PostgreSQL is already required for
durable runs, idempotency records, audit records, and the LangGraph
checkpointer. PostgreSQL row locking can support multiple consumers of a
queue-like table with `FOR UPDATE SKIP LOCKED`, with the documented trade-off
that skipped rows provide an inconsistent view and strict FIFO ordering is not
guaranteed.

A LangGraph checkpointer cannot replace delivery state. It records graph
progress for a stable thread; it does not prove that an admitted event is
queued, leased, retried, dead-lettered, or awaiting operator action.

## Decision

Use a PostgreSQL durable work queue written transactionally with the accepted
event and run. Workers consume that table directly. Do not deploy a separate
broker or dispatcher for the public sample.

The table serves the transactional-outbox role at admission, but it is a job
queue rather than a broker publication outbox: its rows are claimed by workers,
not published to another transport.

Delivery is at least once. Exactly-once execution is not claimed. Duplicate
workflow attempts are expected and are controlled with stable graph thread IDs,
fenced leases, durable side-effect idempotency records, and adapter receipts.

## Identities and invariants

The exact schema is decided in ADR-0003. It must enforce these logical
identities and invariants:

| Identity | Purpose | Invariant |
| --- | --- | --- |
| Event identity | Deduplicate admission | One canonical event per `(scope, source, idempotency_key)` |
| Event fingerprint | Detect key reuse with changed content | The same identity with a different canonical fingerprint is a conflict |
| Run ID | Address the user-visible workflow run | A duplicate accepted event returns the original run ID |
| Thread ID | Address LangGraph checkpoints | Stable and derived from the run ID; unchanged across retries and approval resume |
| Delivery job ID | Address one queued operation | Immutable; attempts and leases update the same job |
| Lease token | Fence one claim attempt | Every heartbeat and completion update matches the current token |
| Side-effect key | Deduplicate one logical external effect | Stable across graph/job replay and separate from the lease token |
| Approval version | Deduplicate one resume decision | At most one resume job for a run and approval version |

Payload canonicalization and fingerprint fields are defined with the versioned
event contract in B01. Transport timestamps, credentials, and caller-generated
correlation metadata must not make two otherwise identical events appear
different.

## Admission transaction

For a valid, authenticated, authorized event, one database transaction:

1. reserves the event identity;
2. persists the bounded canonical event and fingerprint;
3. creates the run in `queued` state;
4. creates one `invoke` delivery job in `pending` state;
5. writes the admission audit record;
6. commits before the API returns an accepted run ID.

No workflow, model, MCP, or notification call occurs inside this transaction.

Duplicate behavior:

- same identity and same fingerprint: return the existing run ID and state;
- same identity and different fingerprint: return a conflict and record a
  bounded audit/security event without overwriting the original;
- database outcome unknown to the caller: the caller retries with the same key
  and receives one of the two deterministic outcomes above.

Invalid, oversized, unknown-version, unauthenticated, or unauthorized requests
are rejected before creating a run or job. Security logging must not preserve
the rejected raw payload or credentials.

## Job state machine

```text
pending ---------+
                 |
retry_wait ------+--> leased --------> completed
                 |      |
expired lease ---+      +------------> failed_terminal
                        |
                        +------------> dead_lettered
                        |
                        +------------> quarantined
```

| State | Meaning | Automatic claim allowed? |
| --- | --- | --- |
| `pending` | Never claimed and available at or after `available_at` | Yes, when due |
| `leased` | Owned temporarily by one worker/token | Only after `lease_expires_at` |
| `retry_wait` | Retryable failure with persisted next-attempt time | Yes, when due |
| `completed` | Invocation reached success or a durable human interrupt | No |
| `failed_terminal` | Non-retryable run failure | No |
| `dead_lettered` | Retry budget exhausted or recovery policy requires operator action | No |
| `quarantined` | Explicit security/policy/poison classification | No |

Terminal job rows are immutable except for bounded retention metadata and
operator annotations. A manual replay creates a new linked job or run according
to ADR-0003; it never erases attempts or resets the original row.

## Run state machine

```text
queued -> running -> succeeded
            |
            +-> waiting_approval --approved--> queued -> running
            |                    |
            |                    +--rejected--> rejected
            |
            +-> retry_wait -> running
            |
            +-> failed_terminal
            +-> dead_lettered
            +-> quarantined
```

The run is the user-facing business/execution summary. The delivery job is the
worker-control record. A job may finish `completed` while its run is
`waiting_approval`; approval creates a new `resume` job for the same run and
thread ID.

Run and job transitions caused by one worker outcome are committed together
and fenced by the active lease token. Checkpoints remain a separate store even
when they share the same PostgreSQL database.

## Claim and lease algorithm

Workers claim a small bounded batch in a short `READ COMMITTED` transaction.
The implementation uses the equivalent of this illustrative statement; ADR-0003
defines actual names and indexes:

```sql
WITH candidate AS (
  SELECT id
  FROM delivery_jobs
  WHERE (
      (
        status IN ('pending', 'retry_wait')
        AND available_at <= transaction_timestamp()
      ) OR (
        status = 'leased'
        AND lease_expires_at <= transaction_timestamp()
      )
    )
    AND attempt_count < :max_attempts
  ORDER BY available_at, created_at, id
  FOR UPDATE SKIP LOCKED
  LIMIT :batch_size
)
UPDATE delivery_jobs AS job
SET status = 'leased',
    lease_token = :new_token,
    lease_owner = :worker_id,
    lease_expires_at = transaction_timestamp() + :lease_duration,
    attempt_count = attempt_count + 1
FROM candidate
WHERE job.id = candidate.id
RETURNING job.*;
```

Requirements:

- claim and lease update occur in the same short transaction;
- no row lock or database transaction is held while a graph runs;
- `ORDER BY` improves fairness but is not advertised as strict FIFO because
  locked rows are skipped;
- every heartbeat, retry, completion, and terminal update includes job ID,
  lease token, and expected `leased` state in its predicate;
- an update affecting zero rows means the worker lost the lease and must not
  commit a result or begin another side effect;
- `UPDATE ... RETURNING` supplies the exact rows claimed by that transaction.

Sample defaults, configurable and tested:

| Setting | Default |
| --- | --- |
| Claim batch size | 1 per available worker concurrency slot |
| Lease duration | 30 seconds |
| Heartbeat interval | 10 seconds |
| Maximum claim attempts | 5 |
| Retry base delay | 1 second |
| Retry cap | 60 seconds |

Long dependency calls do not justify a longer static lease. A worker renews the
lease concurrently through heartbeats. If it cannot renew before expiry, it
cancels local graph work, does not start another side effect, and relies on
recovery/reconciliation.

## Retry policy

Retry classification is deterministic application policy, not an LLM decision.
The persisted error record contains a bounded category and fingerprint, never
raw secret tool output.

| Category | Examples | Outcome |
| --- | --- | --- |
| `retryable_transient` | dependency timeout, rate limit, selected 5xx, connection reset, retryable database conflict | Persist full-jitter backoff and move job/run to `retry_wait` |
| `worker_lost` | process death, missed heartbeat, lease expiry | Reclaim the expired job with a new token and incremented attempt count |
| `terminal_input` | incompatible schema discovered after admission, invalid state invariant, unsupported workflow mapping | `failed_terminal`; no automatic retry |
| `terminal_dependency` | incompatible adapter/tool version, missing capability, malformed or oversized dependency response | `failed_terminal` and dependency readiness false until compatible |
| `terminal_policy` | authorization/evidence/policy violation | `failed_terminal` or `quarantined` according to policy |
| `ambiguous_side_effect` | timeout after a notification request may have been accepted | Reconcile by side-effect key; never blind-retry |
| `poison_or_security` | explicitly classified malicious content, repeated invariant failure for one event, unsafe serialization | `quarantined`; operator review required |

For retryable attempt number `n`, calculate and persist full-jitter delay outside
graph state:

```text
upper_bound = min(retry_cap, retry_base * 2 ** (n - 1))
delay = uniform(0, upper_bound)
available_at = database_now + delay
```

Tests inject the clock and jitter source. Once persisted, `available_at` is the
authority; workers do not recalculate it. When the outcome of the fifth claim
would otherwise be retried, the job and run become `dead_lettered` unless a
stricter terminal/quarantine rule applies. A maintenance transition also
dead-letters an expired fifth lease so it cannot remain stranded or be claimed
a sixth time.

## Human interruption and resume

An interrupt does not retain a worker lease:

1. the graph durably checkpoints the interrupt under the stable thread ID;
2. the worker atomically marks the invocation job `completed` and the run
   `waiting_approval`;
3. the authenticated approval transaction records actor, reason, decision,
   approval version, action hash, and audit entry;
4. rejection closes the run without a new job;
5. approval creates one `resume` job and moves the run to `queued` in the same
   transaction;
6. the worker resumes the same thread with a server-constructed bounded
   `Command(resume=...)`; callers cannot submit arbitrary graph state or tools.

Repeated, stale, altered, expired, or unauthorized approvals create no resume
job. ADR-0004 defines the identity and authorization policy in detail.

## Failure recovery

| Failure point | Durable outcome and recovery |
| --- | --- |
| API dies before admission commit | Nothing was accepted; caller retries the same idempotency key |
| API dies after commit but before response | Duplicate admission returns the existing run ID |
| Worker dies before claim commit | No lease exists; another worker can claim normally |
| Worker dies after claim, before graph work | Lease expires and a new fenced attempt reclaims the job |
| Worker dies during graph execution | Checkpointed work resumes on the same thread after lease expiry |
| Worker dies after checkpoint but before job completion | Replay uses the same checkpoint; completion is fenced |
| Worker dies around an external side effect | Durable side-effect key/receipt controls reconciliation; the queue alone cannot provide exactly-once effects |
| Database fails while idle/claiming | No job is removed; worker backs off and readiness fails |
| Database/heartbeat fails during work | Worker stops new effects, cancels local work, and lets the lease become recoverable |
| Approval API dies before its transaction commits | No resume exists; the same approval request can be retried idempotently |
| Approval API dies after commit | Duplicate approval returns the recorded outcome and does not enqueue twice |

## Dead-letter and quarantine operations

- Dead-letter and quarantine counts are durable operational metrics and alerts,
  not merely logs or traces.
- Records expose bounded error category, fingerprint, attempt history, run ID,
  and event locator; raw payloads and secret outputs are excluded from operator
  lists.
- Automatic replay is forbidden.
- An authorized operator records a reason and chooses retry, create-linked-run,
  or close. The action is audited and idempotent.
- A quarantined event requires security/policy review before any replay.
- Bulk replay is out of scope for the public sample.

## Polling and wake-up

Workers poll due rows with bounded exponential idle backoff and jitter. A future
PostgreSQL `LISTEN/NOTIFY` hint may reduce idle latency, but notifications are
only wake-up hints; the durable table remains authoritative and workers must
poll after startup and reconnect.

## Alternatives considered

### PostgreSQL durable queue consumed directly

Accepted. It provides one admission transaction, simple local operations, and
adequate bounded concurrency for the sample without another service.

### Transactional outbox plus external broker

Deferred. It adds a publisher, broker delivery semantics, more credentials,
more failure states, and another local dependency before throughput or
cross-system fan-out requires them.

### In-memory FastAPI background tasks or `asyncio.Queue`

Rejected. A successful API response could outlive its only copy of the work,
and process restart would lose admission, ordering, retries, and auditability.

### LangGraph checkpointer as the delivery queue

Rejected. Checkpoints answer where graph execution can resume; they do not own
event admission, claims, retry schedules, dead letters, or poison quarantine.

## Broker migration path

Reconsider a broker when measured queue delay, claim contention, independent
scaling, cross-region delivery, or fan-out cannot meet an approved requirement.

Migration preserves the admission transaction and event/run identities:

1. add broker-publication state to the outbox/job contract;
2. add a separate dispatcher that claims unpublished rows with the same fenced
   lease pattern;
3. publish a stable job ID as the broker message idempotency key;
4. record publication receipt before marking the row published;
5. keep consumer processing at least once and side effects idempotent;
6. dual-run and reconcile Postgres and broker delivery before cutting over.

The broker never becomes the audit ledger, workflow checkpoint, or side-effect
receipt store.

## Consequences

### Benefits

- Admission and durable queuing share one atomic transaction.
- The public sample needs only one durable infrastructure dependency.
- Multiple workers can claim without holding locks during graph execution.
- Lease expiry, retry schedule, and dead-letter state are inspectable and
  testable.
- A later broker can be introduced without changing event and run identity.

### Costs and risks

- PostgreSQL carries both application persistence and queue polling load.
- `SKIP LOCKED` does not provide strict FIFO ordering.
- Leases, heartbeats, fencing, retry scheduling, and maintenance must be
  implemented correctly.
- Long-running calls require a healthy heartbeat path.
- Database unavailability stops both admission and work claiming.
- This topology is not intended for unmeasured high-throughput or cross-region
  delivery requirements.

## Verification required by later tasks

- Concurrent claimers never receive the same active lease token.
- Expired leases are reclaimed and stale workers cannot complete them.
- Admission commit/rollback and duplicate-key conflict behavior are atomic.
- Full-jitter retry timestamps are persisted and maximum attempts dead-letter.
- Invalid requests create no run/job; poison events quarantine without retry.
- Worker termination at every failure point follows the recovery table.
- Approval and resume are atomic and enqueue exactly one resume job.
- Queue replay cannot duplicate one logical local notification.
- Queue delay and dead-letter depth are observable without using telemetry as
  the source of truth.

## References

- [PostgreSQL `SELECT` locking and `SKIP LOCKED`](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE)
- [PostgreSQL `UPDATE ... RETURNING`](https://www.postgresql.org/docs/current/sql-update.html)
- [ADR-0001: Async runtime and lifecycle](0001-async-runtime-and-lifecycle.md)
- [ADR-0003: Persistence, checkpoints, and retention](0003-persistence-checkpoints-and-retention.md)
- [ADR-0004: Authentication, authorization, and replay](0004-authentication-authorization-and-replay.md)
- [ADR-0006: External adapter contracts](0006-external-adapter-contracts.md)
- [Repository architecture](../architecture.md)
- [Production productization review](../production-productization-review.md)
