# ADR-0001: Async Runtime and Lifecycle Boundary

- Status: accepted for the public hackathon sample
- Date: 2026-07-30
- Decision owners: Repository Owner and Repository Maintainer (sample roles)
- Scope: API process, dispatcher, worker, workflow invocation, and adapters
- Supersedes: none

## Context

The current reference implementation is synchronous:

- adapter protocols expose regular methods;
- workflow nodes call those methods directly;
- `WorkflowRegistry.invoke()` calls the graph with `invoke()`;
- the CLI owns a short-lived process and explicitly shuts down observability.

The planned service introduces concurrent network and database I/O through an
API, outbox dispatcher, worker pool, Postgres checkpointer, read-only service
graph client, model gateway, and notification adapter. Running those calls
synchronously in an async web server would block its event loop or require a
large implicit thread-pool boundary. Maintaining independent sync and async
production ports would double contract and test behavior.

LangGraph supports synchronous and asynchronous nodes and exposes async graph
invocation. FastAPI supports application resource ownership through an async
lifespan context. Python 3.11 supplies structured concurrency and cancellation
semantics suitable for the repository's minimum Python version.

## Decision

Use an async production runtime from transport through every I/O-bearing port.
Keep deterministic, CPU-light graph logic synchronous where it does not perform
I/O.

### Runtime boundaries

1. The API and each worker process own one `asyncio` event loop.
2. FastAPI endpoints and lifespan hooks are async. Request handlers validate,
   authorize, persist an event/run/outbox transaction, and return; they never
   start durable workflow work with an in-process background task.
3. The dispatcher and worker are separate long-lived async process roles. A
   combined local-demo process may host both only through the same explicit
   lifecycle components and shutdown rules.
4. Production graph execution uses `await graph.ainvoke(...)`. Streaming may use
   `astream(...)` later, but streaming is not required for the first slice.
5. Every port that may cross a process, network, database, model, filesystem,
   or side-effect boundary exposes awaitable methods. Demo adapters implement
   the same async protocols even when they return immediately.
6. Pure parsing, validation, routing, policy, evidence verification, and state
   transformations remain regular functions. A graph may therefore contain
   both sync deterministic nodes and async I/O nodes.

The intended call path is:

```text
async API admission
  -> durable outbox
  -> async dispatcher
  -> async worker
  -> WorkflowRegistry.ainvoke
  -> mixed graph
       sync deterministic nodes
       async adapter nodes
```

### Registry and CLI contract

Add `WorkflowRegistry.ainvoke()` as the authoritative invocation method. It
must preserve the current validation, stable thread ID, observability context,
result scoring, and exception behavior.

The user-facing CLI remains a synchronous entry point but creates the event
loop once at its outermost boundary with `asyncio.run()`. Library and adapter
code must never call `asyncio.run()`, create a nested loop, or conditionally
switch between sync and async behavior.

If a temporary synchronous compatibility method is retained, it is a thin CLI
wrapper over `ainvoke()` and must fail clearly when called from an active event
loop. It is not a production service interface and will be removed before G2.

### Blocking libraries

Prefer native async clients. When a required read-only library has no async API,
isolate it inside its adapter with `asyncio.to_thread()` or a bounded executor.
That exception requires:

- an adapter-specific concurrency limit;
- an outer timeout and explicit error classification;
- no event-loop access from the blocking function;
- no credentials or clients placed in workflow state;
- a replacement issue for any hot-path dependency.

Thread offloading does not make a call safely cancellable. Do not use it as the
normal boundary for mutations or non-idempotent side effects because cancelling
the awaiter does not prove that the underlying operation stopped.

### Concurrency and backpressure

- Use structured, owned tasks; do not create orphan tasks with untracked
  `asyncio.create_task()` calls.
- Use `asyncio.TaskGroup` only when sibling operations have a shared lifetime
  and failure policy.
- Bound worker-run concurrency and every dependency's in-flight calls.
- Never use an unbounded `gather()` over events or evidence requests.
- The durable delivery ADR defines leases, retries, dead letters, and recovery;
  in-memory tasks are not a queue.

### Timeouts and cancellation

Apply timeouts at dependency-attempt boundaries and, where appropriate, at the
overall workflow attempt boundary. Timeout values are configuration, not graph
state. Timeout and retry classification will be specified by the delivery ADR.

Cancellation means the process is trying to stop local work; it is not a
business outcome and does not prove that an external call or side effect was
cancelled. Coroutines must:

1. use `try/finally` for local resource cleanup;
2. propagate `asyncio.CancelledError` after cleanup;
3. avoid converting cancellation into a successful or terminal workflow state;
4. rely on durable run/lease/idempotency records for recovery and reconciliation.

### Resource ownership

Create long-lived resources once per process, outside graph state:

- database pool and repositories;
- async checkpointer connection/pool;
- broker client or Postgres dispatcher resources;
- HTTP/MCP and model clients;
- observability backend;
- concurrency limiters.

FastAPI owns API resources through its lifespan context. The worker and
dispatcher use an equivalent top-level async context manager. Resources close
in reverse dependency order.

Workflow state contains only bounded serializable values and identifiers. It
must never contain live clients, tasks, event loops, connection pools, context
managers, or credentials.

### Startup and shutdown

Startup order:

1. validate settings without printing secrets;
2. create resource pools and clients;
3. verify only dependencies required for that process role;
4. build services, registry, and compiled graphs;
5. declare readiness and begin admission or claiming work.

Graceful shutdown order:

1. fail readiness and stop accepting new work;
2. stop new outbox/queue claims;
3. allow owned in-flight operations to finish within a configured grace period;
4. cancel remaining local tasks and propagate cancellation;
5. release leases or leave them recoverable according to the delivery ADR;
6. flush bounded telemetry without changing business state;
7. close clients, pools, and the observability backend.

The API must not claim worker readiness. Liveness reports process health;
readiness reports whether that process role can safely accept its next unit of
work.

## Alternatives considered

### Synchronous service and worker boundary

Keep current protocols and execute blocking work directly or through a worker
thread pool.

Rejected because the API, database, broker, MCP/API, and model paths are
I/O-bound; implicit thread use makes cancellation, connection ownership,
concurrency limits, and shutdown harder to reason about. It would also make the
async Postgres checkpointer path an exception to the dominant model.

### Separate synchronous and asynchronous production protocols

Keep synchronous demo/CLI ports and add parallel async production ports and
workflow variants.

Rejected because it creates two behavioral contracts, two workflow paths, and
duplicated contract/resilience testing. Demo adapters are inexpensive to
convert and should exercise the production-shaped async boundary.

### Async production runtime with sync deterministic nodes

Accepted. It aligns the runtime with I/O behavior without turning pure policy
code into unnecessary coroutines.

## Consequences

### Benefits

- I/O concurrency and backpressure are explicit.
- API and worker resource lifecycles share one model.
- Production and demo adapters obey the same port contracts.
- Cancellation and graceful shutdown can be tested at defined boundaries.
- Async Postgres checkpointing and network clients do not require sync bridges.

### Costs and risks

- Existing ports, demo adapters, I/O workflow nodes, registry calls, CLI, and
  tests require migration.
- Tests must await runtime paths or invoke one outer async test helper.
- Accidental blocking calls can stall a process event loop.
- Cancellation requires careful cleanup and must not be confused with durable
  workflow state.
- Concurrency can amplify dependency pressure unless every boundary is bounded.

## Migration plan

1. In B03, add async lifecycle/bootstrap components and resource ownership.
2. Convert port methods and demo adapters to async contracts in one coherent
   change; do not maintain long-lived parallel protocols.
3. Convert only nodes that call ports to `async def`; keep deterministic nodes
   synchronous.
4. Add `WorkflowRegistry.ainvoke()` and move the CLI to one outer
   `asyncio.run()` boundary while preserving current behavior.
5. Update tests to exercise async invocation, cancellation propagation, and
   resource cleanup without requiring external services.
6. In B10-B11, make the worker and async Postgres checkpointer the authoritative
   production execution path and remove any temporary sync compatibility API.
7. In each C-track adapter, prohibit blocking network clients unless the
   documented bounded compatibility exception is approved.

## Verification required by later tasks

- A slow adapter does not block an unrelated admitted run.
- Configured dependency and run concurrency limits are enforced.
- Cancellation is re-raised after cleanup and the run remains recoverable.
- Shutdown stops new claims, drains within the grace period, and closes every
  resource exactly once.
- Telemetry shutdown failure does not alter run state or process exit policy.
- API liveness and readiness differ from worker dependency health.
- No production path calls `asyncio.run()` from an active event loop.
- Blocking compatibility adapters are bounded and have explicit timeouts.

## References

- [LangGraph Graph API: async nodes and `ainvoke`](https://docs.langchain.com/oss/python/langgraph/use-graph-api#async)
- [LangGraph async Postgres checkpointer example](https://docs.langchain.com/oss/python/langgraph/add-memory#use-in-production)
- [FastAPI lifespan events](https://fastapi.tiangolo.com/advanced/events/)
- [Python 3.11 task cancellation and task groups](https://docs.python.org/3.11/library/asyncio-task.html)
- [Repository architecture](../architecture.md)
- [Production productization review](../production-productization-review.md)
