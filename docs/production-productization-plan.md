# Production Productization Plan

> Review status: direction accepted with sequencing changes; implementation is
> awaiting approval. See the
> [review and commit-sized execution backlog](production-productization-review.md).

## Purpose

Turn `platform-agent-orchestrator` from a tested reference control plane into an adopted internal Agentic Operations Platform. The first production product is alert intelligence; later releases expand the same control plane to SRE ticket execution, knowledge refresh, and engineering assistance.

This plan is designed to create real company value and evidence for both:

- Senior Product Engineer, Agentic AI: product ownership, 0→1 delivery, stakeholder alignment, adoption, metrics, and platform expansion.
- Senior Software Engineer, Agentic AI Systems: Python services, distributed execution, retrieval, tools, evaluation, reliability, and long-term ownership.

## Current baseline

Implemented:

- Four LangGraph workflows: alert analysis, knowledge refresh, SRE execution, and engineering assistance.
- Typed events, evidence, decisions, approvals, actions, and artifacts.
- Ports/adapters boundary separating orchestration from domain systems.
- Human interruption before risky actions.
- Idempotency keys at event and side-effect boundaries.
- Optional Langfuse tracing, redaction, sampling, and delayed scoring.
- Deterministic demo adapters and workflow/contract/observability tests.

Not yet implemented in this repository:

- Production API or webhook receiver.
- Queue/outbox and long-running workers.
- Durable Postgres checkpoints.
- Real knowledge, reasoning, notification, publication, and action adapters.
- Authentication, authorization, tenant/team policy, and audit storage.
- Container/deployment manifests and production SLOs.
- Versioned replay datasets and automated release evaluation.
- Product analytics, adoption metrics, and a documented launch process.

## Product definition

### Product vision

Provide a governed internal platform that converts operational and engineering events into evidence-backed decisions and bounded actions, with human control wherever risk or uncertainty requires it.

### Initial users

- Primary: SRE and on-call engineers reviewing production alerts.
- Secondary: service owners receiving or acting on recommendations.
- Later: developers, QA engineers, product/BA users, and platform teams.

### Initial problem

On-call engineers receive noisy alerts and must manually determine impact, retrieve service context, decide urgency, and prepare actions. Existing alert automation already provides useful components, but orchestration, durable state, evaluation, and product-level metrics are fragmented.

### First production use case

Alert intelligence:

```text
Sentry alert
  → normalize and deterministic suppression
  → retrieve service/runbook/config evidence
  → semantic impact assessment
  → human review for uncertain decisions
  → evidence-backed recommendation
  → deduplicated Teams notification
  → feedback and evaluation
```

### Non-goals for the first release

- Unrestricted autonomous remediation.
- Replacing `sre-alert-agent`, `service-graph-toolkit`, `sre-skills`, or `code-atlas-workbench` domain ownership.
- Building a generic no-code agent builder.
- Long-term autonomous memory without a measured use case.
- Adding more workflows before the first workflow is adopted and measured.

## Repository boundaries

Preserve the existing ownership model:

| Capability | Owner |
| --- | --- |
| Workflow state, routing, approvals, shared contracts | `platform-agent-orchestrator` |
| Alert collection, alert policy, review, Teams delivery | `sre-alert-agent` |
| Service inventory, code/service graphs, read-only MCP | `service-graph-toolkit` |
| SRE runbooks and bounded operational knowledge | `sre-skills` |
| Wiki, source browsing, engineering chat UI | `code-atlas-workbench` |

Adapters may call these systems; do not copy their internal logic into this repository.

## Target production architecture

```text
Sentry / Bitbucket / Jira / Code Atlas
                  |
                  v
       Authenticated FastAPI ingress
       validation + event schema version
                  |
          transactional outbox
                  |
                  v
           queue / event broker
                  |
                  v
          LangGraph worker pool
            |             |
            |             +---- Postgres checkpointer
            |
            +---- read-only service-graph MCP/API
            +---- model gateway / ReasoningPort
            +---- snapshot publication adapter
            +---- Teams/Jira notification adapter
            +---- allow-listed action service (later)
            +---- durable audit/event store
            +---- Langfuse + Prometheus telemetry
```

Required semantics:

- At-least-once event delivery with idempotent processing.
- Stable correlation ID and thread ID across retry and approval resume.
- Checkpoints store execution state, not credentials or full source corpora.
- Outbox/queue stores event delivery state; it is not replaced by the checkpointer.
- External side effects use durable idempotency records.
- Retrieval is read-only by default.
- Mutation tools are separately authorized, allow-listed, audited, and introduced last.
- Telemetry failure cannot alter workflow behavior or business state.

## Implementation phases

## Phase 0 — Product discovery and baselines

### Objectives

- Define the problem, users, initial scope, and measurable success before building the production runtime.
- Create evidence that product priorities came from user and operational needs.

### Work

1. Interview SRE/on-call engineers and service owners.
2. Document their current alert-review workflow, pain points, risks, and trust requirements.
3. Collect a representative historical alert sample with sensitive data removed or access-controlled.
4. Measure the current baseline:
   - alerts received;
   - alerts sent to Teams;
   - alerts suppressed;
   - manual review rate;
   - actionable versus non-actionable decisions;
   - missed actionable alerts;
   - median review time;
   - time from alert to notification;
   - current AI/model cost.
5. Define the launch group and product owner.
6. Agree on first-release success and rollback criteria.

### Documents to add

```text
docs/product/
  vision.md
  users-and-jobs.md
  use-cases.md
  metrics.md
  launch-plan.md
  roadmap.md
```

### Acceptance criteria

- At least three representative user/stakeholder perspectives are documented.
- One beachhead use case and explicit non-goals are agreed.
- Baseline metrics have definitions, data sources, owners, and measurement windows.
- Launch success and stop/rollback conditions are written before rollout.

## Phase 1 — Production service foundation

### Objectives

- Expose workflow invocation through a secure service interface.
- Separate request admission, durable delivery, and workflow execution.

### Proposed package structure

```text
src/platform_agent_orchestrator/
  api/
    app.py
    dependencies.py
    routes/
      events.py
      approvals.py
      feedback.py
      health.py
  runtime/
    settings.py
    bootstrap.py
    worker.py
    lifecycle.py
  persistence/
    database.py
    outbox.py
    idempotency.py
    audit.py
    checkpoints.py
  adapters/
    production/
      reasoning.py
      service_graph.py
      alert_notification.py
      knowledge_publisher.py
  security/
    authentication.py
    authorization.py
    webhook_validation.py
```

The exact structure may change, but keep transport, persistence, orchestration, and domain adapters separate.

### API surface

Minimum endpoints:

```text
POST /v1/events
GET  /v1/runs/{run_id}
POST /v1/runs/{run_id}/resume
POST /v1/runs/{run_id}/feedback
GET  /health/live
GET  /health/ready
GET  /metrics
```

Requirements:

- Validate typed, versioned event envelopes.
- Authenticate callers and verify webhook signatures where applicable.
- Authorize source, workflow, team/tenant, and environment.
- Return an accepted run ID instead of blocking for the full workflow.
- Never accept an arbitrary workflow or arbitrary tool name from an untrusted payload.
- Bound payload size and reject unknown fields.
- Keep credentials out of event payloads and graph state.

### Durable delivery

Implement an outbox plus worker model:

1. API validates and persists the event and outbox record in one transaction.
2. Dispatcher publishes pending outbox entries to the queue.
3. Worker consumes the event and claims the idempotency key.
4. Worker invokes the correct workflow with a stable thread ID.
5. Success, interruption, retry, terminal failure, and side effects are recorded.
6. Duplicate delivery returns the prior result or safely performs no duplicate side effect.

Define:

- retryable versus terminal errors;
- exponential backoff and jitter;
- maximum attempts;
- dead-letter behavior;
- poison-event quarantine;
- recovery after worker termination;
- graceful shutdown and in-flight work handling.

### Checkpointing

- Add a supported Postgres LangGraph checkpointer.
- Test interruption, process termination, restart, and approval resume.
- Prove that an external side effect is not duplicated when a node is replayed.
- Add checkpoint retention and deletion policy.

### Acceptance criteria

- An authenticated event produces an asynchronous workflow run.
- Duplicate events do not duplicate notifications or actions.
- A workflow interrupted for approval survives process restart and resumes correctly.
- Invalid, unauthorized, oversized, and unknown event types are rejected.
- Worker restart and transient dependency failure have tested recovery paths.
- Live, ready, and metrics endpoints reflect real dependency state.

## Phase 2 — Real alert-intelligence adapters

### Objectives

- Replace the alert demo path with real company systems while preserving repository ownership boundaries.

### Adapter order

1. `ServiceGraphKnowledgePort`
   - Call the read-only MCP/API in `service-graph-toolkit`.
   - Return bounded `EvidenceRef` objects with source, locator, revision, confidence, and observed time.
   - Enforce query/result limits, timeouts, and source allow-lists.

2. `AlertReasoningPort`
   - Implement structured model output validated as `AgentDecision`.
   - Separate deterministic policy from semantic judgment.
   - Support model routing, timeouts, bounded retries, and fallback.
   - Reject decisions with invalid or unavailable evidence references.

3. `AlertNotificationPort`
   - Reuse the Teams delivery capability from `sre-alert-agent`.
   - Preserve the existing message contract and idempotency behavior.
   - Store delivery receipt and failure category.

4. Review/approval integration
   - Connect LangGraph interrupts to the existing review experience or a minimal approval API.
   - Record actor, reason, timestamp, decision, original action hash, and resulting run transition.

Do not implement real mutation adapters in this phase.

### Reasoning design

- Use an LLM only for semantic impact judgment and recommendation generation.
- Keep normalization, known-noise policy, thresholding, evidence verification, authorization, and routing deterministic.
- Require structured responses.
- Distinguish model confidence from measured correctness.
- Treat retrieved content as untrusted data, not instructions.
- Limit context size and attach source identifiers to every factual claim.

### Acceptance criteria

- The end-to-end path uses real Sentry-derived events, company knowledge, model reasoning, human review, and Teams delivery.
- Every delivered recommendation has verified evidence or is explicitly marked provisional.
- Unknown/low-confidence cases are reviewed instead of silently suppressed.
- Alert and telemetry payloads are redacted according to company policy.
- Dependency timeout, model failure, retrieval failure, and Teams failure have safe outcomes and tests.

## Phase 3 — Evaluation and release gates

### Objectives

- Replace directional success claims with reproducible, versioned evidence.
- Prevent prompt/model/policy changes from silently degrading reliability or trust.

### Evaluation dataset

Create a protected, versioned replay dataset containing representative cases:

- actionable and non-actionable alerts;
- all important severity classes;
- known-noise patterns;
- ambiguous alerts requiring review;
- dependency and cascading-impact cases;
- retrieval-missing and stale-evidence cases;
- prompt-injection-like content in alert/evidence fields;
- past false positives and false negatives.

Each record should include:

- sanitized input and source revision;
- expected decision or human rubric;
- required/acceptable evidence;
- unacceptable outcomes;
- risk weight;
- dataset version and reviewer.

### Metrics

Quality and trust:

- actionable-alert precision;
- actionable-alert recall;
- false-negative rate, weighted by incident severity;
- priority/severity agreement;
- evidence/citation validity;
- recommendation acceptance;
- human-review agreement;
- unsupported-claim rate;
- unsafe-action proposal rate.

Task and product outcomes:

- task-completion rate;
- automated, reviewed, rejected, and fallback rates;
- time saved per alert;
- alert-to-notification latency;
- user override rate.

System outcomes:

- p50/p95/p99 end-to-end latency;
- retrieval and model latency;
- tokens and model cost per completed task;
- workflow success and recovery rates;
- dependency error rates;
- queue delay and backlog.

### Release process

1. Version prompts, policies, models, tools, contracts, and evaluation datasets.
2. Run deterministic tests and replay evaluation in CI.
3. Compare candidate results with the current production baseline.
4. Block release when safety or agreed quality thresholds regress.
5. Deploy in shadow mode, then canary to a small team or traffic percentage.
6. Compare canary and control metrics.
7. Promote or automatically/manual roll back according to the launch policy.

### Proposed files

```text
evaluation/
  datasets/
  rubrics/
  runners/
  reports/
  README.md

tests/
  unit/
  contract/
  integration/
  replay/
  resilience/
```

Do not commit company-sensitive raw alerts. Store protected datasets in an approved location and keep only schemas, fixtures, and sanitized examples in Git.

### Acceptance criteria

- The same dataset can compare two workflow releases reproducibly.
- Reports include quality, task completion, latency, and cost.
- False-negative and safety regressions can block promotion.
- Every production release records code, prompt, model, policy, tool, and dataset versions.
- Replay results link to the associated pull request or release decision.

## Phase 4 — Human-governed continuous improvement

### Objectives

- Convert real feedback and failures into evaluated improvements without silent self-modification.

### Feedback contract

Add a structured `FeedbackEvent` containing:

- workflow/run/trace identifiers;
- actor role and team;
- correctness or usefulness rating;
- accepted, edited, rejected, or escalated outcome;
- reason category;
- corrected decision or recommendation where appropriate;
- linked incident/ticket outcome;
- privacy classification and retention metadata.

### Improvement workflow

```text
Feedback + failures + overrides
  → group recurring failure patterns
  → propose bounded prompt/rule/tool/retrieval changes
  → generate a human-readable rationale
  → run replay evaluation
  → create a human-reviewed change/PR
  → canary
  → promote or roll back
```

Safety rules:

- The improvement agent cannot directly modify production configuration.
- It cannot weaken authentication, approval, evidence, or audit policy.
- Every proposal includes examples, expected impact, evaluation results, and rollback.
- Human approval is required before merge and promotion.
- Production feedback is access-controlled and redacted.

### Acceptance criteria

- Users can attach structured feedback to a run.
- Recurring failure categories are visible and prioritized.
- A proposed change can be traced from feedback through evaluation and release.
- No agent can silently update its own production prompt, policy, model, or tools.

## Phase 5 — Production operations and security

### Objectives

- Operate the platform as a long-lived, business-critical service.

### Reliability

Define SLIs and SLOs for:

- API availability;
- accepted-event durability;
- workflow terminal-success rate;
- queue delay;
- end-to-end latency by workflow;
- approval-resume success;
- notification delivery;
- checkpoint recovery;
- evidence freshness.

Add:

- Prometheus metrics and Grafana dashboards;
- structured logs with correlation/run IDs;
- Langfuse traces linked to run IDs without exposing secrets;
- dependency health and saturation metrics;
- queue-backlog and dead-letter alerts;
- model budget and rate-limit alerts;
- runbooks for dependency failure, stuck workflows, checkpoint recovery, and rollback.

### Security

- Authenticate human and service callers.
- Authorize by workflow, source, tenant/team, environment, tool, action, and risk.
- Separate read-only retrieval credentials from mutation credentials.
- Use short-lived credentials and an approved secrets manager.
- Validate webhook signatures and prevent replay.
- Encrypt data in transit and at rest.
- Define retention and deletion for events, checkpoints, traces, feedback, and audit records.
- Threat-model prompt injection, tool misuse, data exfiltration, tenant crossover, approval spoofing, and replay attacks.
- Perform a security review before enabling any mutation tool.

### Acceptance criteria

- SLOs, dashboards, alerts, and runbooks exist and are exercised.
- A restore/recovery exercise proves checkpoint and database recovery.
- Authorization and tenant-isolation tests cover positive and negative cases.
- Security review approves the read-only launch scope.
- Mutation remains disabled until its separate review is complete.

## Phase 6 — Product launch and adoption

### Objectives

- Prove that the system is used, trusted, and valuable—not merely deployed.

### Rollout

1. Offline replay against historical data.
2. Shadow production with no user-visible side effects.
3. One-team pilot with mandatory review.
4. Limited auto-send for high-confidence, low-risk cases.
5. Expand to more services/teams based on measured results.

### Product analytics

Track:

- teams and services onboarded;
- weekly/monthly active users;
- workflows completed per period;
- repeat usage and retention;
- review, acceptance, edit, rejection, and override rates;
- time saved and lead-time reduction;
- user-reported trust/usefulness;
- support burden and onboarding time;
- cost per accepted recommendation;
- incidents or escapes attributable to agent decisions.

Segment metrics by workflow, team, service, severity, model/policy version, and release. Do not publish sensitive team comparisons without appropriate context and permission.

### Acceptance criteria

- Pilot users and owners are named.
- Training, documentation, support, and feedback channels exist.
- A launch review compares actual results with the Phase 0 baseline.
- Product decisions and roadmap changes are linked to user feedback and metrics.
- Expansion requires demonstrated value and acceptable safety/reliability—not only technical readiness.

## Phase 7 — Platform expansion

Begin only after alert intelligence has measurable adoption and reliable operations.

### Platform capabilities

- Replace hardcoded workflow lookup with an explicit, controlled workflow/use-case registry.
- Add versioned workflow, event, prompt, model, tool, and policy metadata.
- Add per-use-case and per-team model/tool policy.
- Provide reusable onboarding templates and contract tests for new adapters.
- Add model routing and fallback based on quality, latency, cost, and data policy.
- Add quota, concurrency, and budget controls.
- Provide an internal product/evaluation dashboard.

### Expansion order

1. Knowledge refresh with real Bitbucket events and atomic Code Atlas publication.
2. Engineering assistance using the same revisioned knowledge plane.
3. SRE ticket planning with read-only recommendations.
4. Human-approved, allow-listed SRE actions after independent security and audit validation.

### Multi-agent design rule

Use specialized agents only where different roles, tools, policies, or evaluation criteria justify them. Do not create an agent swarm for presentation value. Deterministic nodes should continue to own parsing, routing, policy, authorization, validation, and side-effect control.

## Testing strategy

### Unit tests

- Contract validation and schema compatibility.
- Routing and policy decisions.
- Idempotency and retry classification.
- Redaction and authorization.
- Metrics and result summarization.

### Contract tests

- Every production adapter against a fake or sandbox server.
- Schema validation for MCP/API/model/Teams responses.
- Backward compatibility across event and artifact versions.

### Integration tests

- API → outbox → queue → worker → checkpoint → adapter.
- Interrupt → restart → resume.
- Duplicate delivery and duplicate side-effect prevention.
- Dependency timeout, retry, fallback, and dead-letter behavior.

### Replay/evaluation tests

- Historical and adversarial cases.
- Model/prompt/policy comparisons.
- Quality, safety, latency, and cost thresholds.

### Resilience tests

- Worker termination during each workflow phase.
- Database, queue, retrieval, model, and notification outages.
- Slow dependencies and backpressure.
- Corrupt/invalid events and stale approvals.

## Delivery backlog

### P0 — Required for the first production pilot

- Product discovery, baselines, success criteria, and launch group.
- Versioned event envelope and secure asynchronous API.
- Outbox/queue/worker execution.
- Postgres checkpointer and durable idempotency/audit records.
- Real alert knowledge, reasoning, review, and Teams adapters.
- Replay dataset and quality/safety release gates.
- Prometheus/Langfuse observability, dashboards, and runbooks.
- Container/deployment configuration and CI/CD.
- Shadow mode and one-team pilot.

### P1 — Required for controlled expansion

- Structured feedback API and product analytics.
- Human-governed improvement proposal workflow.
- Model routing/fallback and cost controls.
- Workflow/use-case registry and adapter contract-test kit.
- Knowledge-refresh and engineering-assistance production adapters.

### P2 — Only after safety and adoption evidence

- Allow-listed SRE mutation service.
- Fine-grained approval policy and action audit UI.
- More teams, sources, and workflows.
- Advanced memory only for an evaluated product requirement.

## Product decision record

For every meaningful roadmap or architecture decision, record:

- user/problem evidence;
- options considered;
- technical and product trade-offs;
- security/reliability implications;
- decision owner and stakeholders;
- expected metric impact;
- validation date and rollback/revisit condition.

This creates evidence of technical product judgment and influence, not just implementation activity.

## Evidence to capture for future CV and interviews

Collect these facts throughout delivery:

- Personal ownership: product decisions, architecture, implementation, launch, and operations.
- Number and roles of stakeholders/users interviewed.
- Teams/services/users onboarded and workflow volume.
- Baseline versus post-launch manual effort and lead time.
- Evaluation dataset size, composition, review method, and time window.
- Precision, recall, false-negative, acceptance, and task-completion results.
- p95 latency, availability, recovery rate, and cost per successful task.
- Real failure or incident and the lasting improvement it caused.
- A prioritization decision: what was deliberately not built and why.
- A prototype-to-production story covering contracts, persistence, security, evaluation, rollout, and adoption.

Do not put placeholders or unverified numbers in a CV. Keep sensitive company data generalized or sanitized according to policy.

## Possible CV wording after the evidence exists

Use only after implementation and measurement:

> Defined and led the 0→1 launch of an internal agentic operations platform, productizing LangGraph workflows across alert intelligence, SRE automation, knowledge refresh, and engineering assistance.

> Established versioned replay evaluation and release gates covering actionable-alert recall, task completion, evidence validity, reliability, latency, and cost.

> Built a human-governed continuous-improvement loop that converted production feedback into evaluated, canary-released policy and prompt updates.

> Expanded adoption to X teams and Y monthly workflows, reducing alert-review time by Z% while maintaining an actionable-alert recall of N%.

Replace `X`, `Y`, `Z`, and `N` only with measured, approved values.

## Recommended execution order for the next session

1. Approve or amend the assumptions in the linked review.
2. Execute its Track A commits and pass design Gate G1.
3. Implement its local vertical slice and pass Gate G2 before connecting real systems.
4. Connect the read-only alert adapters and pass offline evaluation Gate G3.
5. Run shadow mode and collect baseline/candidate measurements.
6. Launch a mandatory-review one-team pilot, review results, and only then expand.
