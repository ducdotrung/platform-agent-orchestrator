# Production Productization Plan Review and Execution Backlog

Status: reviewed on 2026-07-30. A01-A08 and B01-B05 are complete and Gate G1
passed for the synthetic hackathon sample; B06 is next. Gate G0/G1 must be
repeated before company use.

This document reviews
[the productization plan](production-productization-plan.md) against the current
repository and turns it into small, reviewable delivery tasks. Each task below
is intended to be one commit. A task may be split further if implementation
reveals unrelated changes, but separate tasks should not be combined into one
commit.

## Review outcome

The plan has the right product direction and safety posture. Alert intelligence
is a sensible first vertical slice, the repository boundaries are clear, and
the plan correctly separates workflow checkpoints, event delivery, audit data,
and telemetry.

The plan should be approved with the following sequencing changes:

1. Treat discovery, security, operations, and evaluation as parallel
   workstreams with release gates, not as concerns deferred to Phases 3-6.
   Authentication, data classification, baseline evaluation, and minimum
   operational signals are prerequisites for connecting real data.
2. Keep alert collection and policy in `sre-alert-agent`. For the first slice,
   this service should accept a versioned alert event produced by that system;
   it should not become another direct Sentry integration.
3. Build a thin end-to-end slice with demo/fake adapters before adding all P0
   infrastructure. Prove admission, durable delivery, interruption/resume, and
   side-effect deduplication before connecting real adapters.
4. Decide the runtime boundaries before coding. The current ports and registry
   are synchronous, while the proposed API, queue workers, MCP/API calls, and
   model calls naturally involve asynchronous I/O. Mixing both models without
   an explicit boundary will complicate shutdown, retries, and tests.
5. Specify durable semantics before implementing the outbox. The design needs
   authoritative state transitions, uniqueness constraints, lease recovery,
   retry classification, and the relationship among event identity, run
   identity, graph thread identity, and side-effect identity.
6. Move durable side-effect claims outside replay assumptions. The existing
   alert graph calls the notification port inside a replayable node; a
   production adapter needs a durable claim/result record so a crash after
   delivery cannot cause an unbounded duplicate.
7. Replace the open `dict[str, Any]` event payload at the ingress boundary with
   versioned, event-specific payload models. Internal graph state may remain a
   serialization-friendly mapping, but it must originate from validated input.
8. Split repository work from cross-repository and organizational work. This
   repository can define and test adapter contracts, but changes to source
   indexing, alert delivery/policy, runbooks, and the wiki belong to their
   owning repositories.

## Decisions required before implementation

Record each decision as an ADR. Do not infer these choices from the illustrative
architecture diagram.

| Decision | Why it blocks work | Minimum options to compare |
| --- | --- | --- |
| Pilot scope and owner | Defines success, rollback, and who accepts risk | alert intelligence only; launch team; product/operational owner |
| Runtime I/O model | Changes ports, registry calls, workers, and tests | synchronous worker boundary; async end to end |
| Durable delivery | Determines schemas and operational burden | Postgres-backed job/outbox; outbox plus an existing company broker |
| Deployment target | Determines health, identity, secrets, and manifests | the company's supported container/runtime platform |
| Service and human identity | Determines event admission and approval security | gateway-issued identity; service tokens; workload identity; company SSO |
| Tenancy boundary | Determines authorization and data keys | single launch team; explicit team/service scope; future multi-tenant path |
| Data classification and retention | Governs events, checkpoints, evidence, feedback, audit, and traces | approved classes, locations, retention periods, deletion owner |
| External adapter contracts | Prevents domain logic from leaking into this repository | HTTP/MCP schemas, timeout/error model, idempotency receipts, versioning |

Recommended first-pilot simplification: use one explicitly authorized launch
team and one alert workflow. Do not claim general multi-tenancy until isolation
requirements and tests exist.

## Release gates

Implementation order is controlled by gates rather than the phase numbers in
the product plan.

| Gate | Evidence required to pass |
| --- | --- |
| G0 — Scope | Alert intelligence, owners, users, non-goals, baseline window, success thresholds, and rollback conditions are approved. |
| G1 — Design | Runtime, delivery, persistence, auth, tenancy, data, and adapter ADRs are approved; threat model covers the read-only pilot. |
| G2 — Local vertical slice | Authenticated fake/demo event travels through durable admission and a worker; restart/resume and duplicate-delivery tests pass. |
| G3 — Offline candidate | Real adapters pass contract tests; a sanitized replay report meets agreed safety and quality thresholds. |
| G4 — Shadow | Production traffic is processed without user-visible delivery; reliability, quality, latency, and cost are reviewed. |
| G5 — Reviewed pilot | One team uses mandatory human review; support, rollback, audit, dashboards, and runbooks are exercised. |
| G6 — Bounded auto-send | Only approved low-risk cases auto-send; canary results meet the launch policy. |

No mutation tool is part of G0-G6.

## Commit-sized execution backlog

### Track A — Scope and architecture

| ID | Commit deliverable | Verification | Depends on |
| --- | --- | --- | --- |
| A01 | Add Phase 0 product document templates with owners, evidence links, and `TBD` fields rather than invented claims. | Documentation links and required fields reviewed. | None |
| A02 | Record approved pilot scope, metric definitions, baseline window, success thresholds, and rollback criteria. The public sample must label synthetic assumptions explicitly. | G0 sample checklist approved by repository roles; repeat with real stakeholders before company use. | Public sample decision, A01 |
| [A03](adr/0001-async-runtime-and-lifecycle.md) | Add ADR for the runtime I/O model and lifecycle boundary. | ADR includes alternatives, consequences, and migration effect on current ports. | A02 |
| [A04](adr/0002-postgres-durable-delivery.md) | Add ADR for outbox/queue topology and failure semantics. | State machine, leases, retries, dead letters, and recovery behavior are specified. | A02 |
| [A05](adr/0003-persistence-checkpoints-and-retention.md) | Add ADR for Postgres schemas, checkpointing, idempotency, side effects, audit, and retention ownership. | Store boundaries and transaction boundaries are unambiguous. | A04 |
| [A06](adr/0004-authentication-authorization-and-replay.md) | Add ADR for authentication, approval identity, authorization, launch-team scope, and replay protection. | Positive/negative authorization cases are listed. | A02, deployment input |
| A07 ([deployment](adr/0005-local-compose-deployment.md), [adapters](adr/0006-external-adapter-contracts.md)) | Add ADRs for deployment and external adapter contracts. | Enabled sample adapters are local or consume an existing public read-only contract; future external APIs and cross-repository changes still require owner approval. | A03-A06 |
| [A08](security/read-only-pilot-threat-model.md) | Add a read-only-pilot threat model and data-flow/classification document. | Security review covers prompt injection, exfiltration, spoofing, replay, and retention. | A05-A07 |

Gate G1 passed for the public sample after A08; implementation starts at B01.

### Track B — Shared contracts and service foundation

| ID | Commit deliverable | Verification | Depends on |
| --- | --- | --- | --- |
| B01 | Add a versioned event envelope and typed alert payload while preserving an explicit migration path for current callers. | Unit tests reject extra, unknown, oversized, and incompatible fields. | G1 |
| B02 | Add run, delivery, retry, approval, feedback, and error contracts with explicit public-safe serialization. | Schema and compatibility tests cover every state and redaction rule. | B01 |
| B03 | Add validated settings and dependency bootstrap without real credentials in graph state. | Startup tests cover missing/invalid configuration and safe defaults. | A03, B01 |
| B04 | Add the FastAPI application with live/readiness endpoints and request-size/error handling. | API tests distinguish process liveness from admission readiness. | B03 |
| B05 | Add authentication, source/workflow/team authorization, and webhook replay protection at admission. | Positive and negative API security tests pass. | A06, B04 |
| B06 | Add database models and migrations for events, runs, outbox entries, idempotency claims, side-effect receipts, approvals, and audit records. | Migration upgrade test and uniqueness/retention constraint tests pass. | A05, B02 |
| B07 | Add the transactional event repository and outbox claim/lease state machine. | Transaction rollback, concurrent claim, expired lease, and duplicate-key tests pass. | B06 |
| B08 | Add `POST /v1/events` and `GET /v1/runs/{run_id}` using deterministic event-to-workflow routing. | Authenticated requests return stable run IDs; duplicates return the existing run. | B05, B07 |
| B09 | Add the dispatcher/broker abstraction and the chosen implementation. | Publish retry, duplicate publication, shutdown, and poison-record tests pass. | A04, B07 |
| B10 | Add worker lifecycle and run-state transitions around the existing registry. | Tests cover success, interruption, retryable failure, terminal failure, and worker termination. | B03, B09 |
| B11 | Add the supported Postgres LangGraph checkpointer and stable thread-ID mapping. | A process-restart test resumes the same interrupted run. | B06, B10 |
| B12 | Add durable side-effect execution/receipt handling and connect demo notification through it. | Crash/replay tests prove one logical notification for duplicate node execution. | B07, B10 |
| B13 | Add authenticated approval listing/resume with actor identity, reason, action hash, expiry, and optimistic concurrency. | Stale, altered, expired, unauthorized, and repeated approvals are rejected. | B05, B11 |
| B14 | Add structured feedback ingestion and trace/run association without making telemetry authoritative. | Contract, authorization, retention, and unavailable-telemetry tests pass. | B02, B05, B06 |
| B15 | Add Prometheus metrics and structured public-safe logs for API, outbox, worker, run, approval, and side-effect states. | Metric cardinality/redaction tests and dependency-state health tests pass. | B08-B14 |
| B16 | Add container, deployment, migration-job, graceful-shutdown, and CI configuration for the chosen platform. | Build, startup, migration, signal handling, and smoke checks pass. | A07, B15 |

Gate G2 follows B16. B14 may be postponed until after G2 if feedback is not
needed for the local slice; it remains required before G5.

### Track C — Real read-only alert slice

All external changes remain in their owning repositories and should be linked
from the relevant ADR or issue rather than copied here.

| ID | Commit deliverable | Verification | Depends on |
| --- | --- | --- | --- |
| C01 | Add the `sre-alert-agent` ingress contract adapter/fixture for a Sentry-derived alert event; do not collect Sentry directly here. | Consumer-driven contract tests cover versioning, signatures, replay, and sanitized fixtures. | G2, external producer contract |
| C02 | Add the bounded read-only `service-graph-toolkit` knowledge adapter. | Sandbox contract tests cover source allow-lists, result limits, stale evidence, timeout, and malformed data. | G2, external knowledge contract |
| C03 | Add the structured alert reasoning adapter with evidence-ID validation, model timeout/budget limits, and deterministic fallback. | Fake-gateway and adversarial tests cover malformed output, unknown citations, injection content, timeout, and budget exhaustion. | C02, evaluation rubric |
| C04 | Add the `sre-alert-agent` notification adapter behind durable side-effect handling. | Contract tests cover accepted receipt, duplicate key, retryable/terminal failure, and ambiguous timeout. | B12, external delivery contract |
| C05 | Connect real adapter selection through bootstrap and preserve demo adapters for deterministic tests. | End-to-end test exercises alert -> evidence -> decision -> review -> receipt with fake external servers. | C01-C04, B13 |
| C06 | Enforce provisional/review behavior for missing, stale, invalid, or low-confidence evidence. | No such case is silently suppressed or auto-sent in workflow tests. | C03, C05 |

### Track D — Evaluation and release controls

| ID | Commit deliverable | Verification | Depends on |
| --- | --- | --- | --- |
| D01 | Add replay dataset schema, rubric schema, sanitized examples, protected-dataset locator convention, and version metadata. | Validation tests reject sensitive/invalid fixtures and missing provenance. | A02, A08 |
| D02 | Add deterministic replay runner and report format for quality, safety, latency, token use, and cost. | The same inputs/config produce comparable versioned reports. | D01, C05 |
| D03 | Add threshold comparison and CI release-gate command. | A seeded false-negative or unsafe regression fails the gate. | D02 |
| D04 | Add resilience tests for process death and database, broker, retrieval, model, and notification failures. | Recovery outcomes match the ADR state machines with no duplicate logical side effect. | B12, C05 |
| D05 | Add release metadata tying code, contract, prompt, model, policy, tool, and dataset versions together. | Every report and run exposes the immutable release identifier. | D02, B10 |

Gate G3 follows D05.

### Track E — Operate, launch, and learn

| ID | Commit deliverable | Verification | Depends on |
| --- | --- | --- | --- |
| E01 | Add SLO definitions, dashboards, alert rules, and runbooks for the read-only alert slice. | Failure, backlog, restore, stuck-run, and rollback exercises are recorded. | B15, D04 |
| E02 | Add explicit shadow mode that suppresses external notification while retaining candidate outcomes and evaluation links. | Production-like test proves zero user-visible side effects. | C05, D05 |
| E03 | Add deployment promotion/rollback controls and pilot configuration restricted to the approved team/services. | Authorization and rollback smoke tests pass. | B16, E01-E02 |
| E04 | Record the shadow review and G4 decision using measured results. | Quality, reliability, latency, cost, and data/security findings have owners. | Shadow observation window |
| E05 | Enable mandatory-review pilot configuration and publish onboarding/support material. | Approval, audit, support, and rollback paths are exercised with pilot owners. | G4, E03 |
| E06 | Add product analytics derived from business records, with privacy-safe dimensions and metric definitions. | Dashboard values reconcile with sampled runs; telemetry is not the audit source. | B14, pilot metric definitions |
| E07 | Record the reviewed-pilot outcome and G5 decision. | Actual results are compared with baseline and rollback criteria. | Pilot observation window |
| E08 | If G5 approves it, add allow-listed auto-send policy for agreed low-risk cases and canary controls. | Policy, authorization, replay, and rollback tests pass; all other cases still require review. | G5 |

## Deferred work

The following are deliberately outside the first production slice:

- knowledge-refresh and engineering-assistance production adapters;
- SRE action execution or any mutation tool;
- a generic workflow/plugin platform;
- broad multi-tenancy;
- autonomous prompt, policy, model, or tool changes;
- long-term agent memory.

Expansion starts only after G5 demonstrates adoption and reliable operation.

## Approval requested

Before starting A01, confirm or amend these assumptions:

1. Alert intelligence is the first and only pilot workflow.
2. `sre-alert-agent` produces accepted alert events and owns Teams delivery.
3. The first pilot is restricted to one launch team and remains read-only apart
   from a governed notification side effect.
4. We will commit each backlog item separately and stop at each release gate
   for explicit approval.
