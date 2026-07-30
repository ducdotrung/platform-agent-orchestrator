# Product Use Cases

Status: UC-01 approved for the public hackathon sample only.

> The product value and user needs are synthetic demo hypotheses. Passing this
> sample does not demonstrate company adoption or production readiness.

## Document control

| Field | Value |
| --- | --- |
| Product owner | Hackathon Product Lead (sample role) |
| Operational owner | Demo Operator (sample role) |
| Technical owner | Repository Maintainer (sample role) |
| Approvers | Repository Owner (sample role) |
| Last reviewed | 2026-07-30 |

## Selection criteria

Score candidate use cases only after evidence is available.

| Criterion | Weight | Scoring rule | Evidence source |
| --- | --- | --- | --- |
| User/operational value | 30% | Score 1-5 against synthetic jobs and handling-time hypothesis | Synthetic perspectives and baseline |
| Frequency | 10% | Score 1-5 against representation in the 24-case scenario set | Synthetic baseline |
| Safety and reversibility | 20% | Score 1-5; local/read-only/reversible scores highest | Sample risk review |
| Evidence availability | 20% | Score 1-5 against public revisioned graph/code evidence | Sock Shop inventory and MCP demo |
| Evaluation feasibility | 10% | Score 1-5 against deterministic replay coverage | Planned replay fixtures |
| Delivery effort | 10% | Score 1-5 where lower bounded effort scores highest | Technical design |

## UC-01 — Alert intelligence

Status: approved beachhead for the public hackathon sample.

### User and outcome

- Primary user: synthetic Sock Shop on-call engineer.
- Trigger: a versioned local alert fixture shaped like the future
  `sre-alert-agent` contract; there is no direct Sentry connection.
- Desired outcome: an evidence-backed recommendation delivered or held for
  review according to deterministic policy.
- Product value hypothesis: evidence enrichment and structured review reduce
  the illustrative median handling time from six to at most 4.5 minutes while
  preserving actionable-alert recall.

### Happy path

1. Validate the event envelope, identity, source, version, and payload limits.
2. Apply deterministic normalization and suppression policy owned by the alert
   system or an explicitly versioned shared contract.
3. Retrieve bounded, read-only service and runbook evidence.
4. Perform structured semantic impact assessment.
5. Verify evidence references and apply deterministic review policy.
6. Obtain human review where required.
7. Request an idempotent notification through `sre-alert-agent`.
8. Record the run, approval, audit, and delivery outcome in their authoritative
   stores; emit redacted telemetry separately.

### Safe fallback paths

| Condition | Required outcome | Approval status |
| --- | --- | --- |
| Unknown or incompatible event | Reject before workflow admission | Approved sample behavior |
| Missing/stale evidence | Mark provisional and require review; do not silently suppress | Approved sample behavior |
| Invalid model output or citation | Reject the decision and follow deterministic fallback | Approved sample behavior |
| Retrieval/model timeout | Retry only when classified retryable, then review/fail safely | Approved sample behavior |
| Ambiguous notification timeout | Reconcile using the durable idempotency receipt before retry | Approved sample behavior |
| Telemetry unavailable | Continue according to business state; never use telemetry for recovery | Approved repository rule |

### Acceptance evidence

| Requirement | Measure/test | Threshold | Owner | Evidence |
| --- | --- | --- | --- | --- |
| Useful recommendations | Synthetic reviewer acceptance rubric | At least 80% | Hackathon Product Lead | Versioned replay report |
| Actionable-alert recall | Replay against 10 actionable cases | At least 90% overall and 100% for critical cases | Demo Operator | Versioned replay report |
| Evidence validity | Referenced evidence is present and supports the bounded claim | 100% | Platform/Safety Reviewer | Replay report |
| Review and delivery safety | Replay/resilience tests | Zero unauthorized or duplicate logical notifications | Repository Maintainer | Test report |
| Review-time improvement | Synthetic baseline versus timed demo | At least 25% median reduction | Hackathon Product Lead | Demo report |

## Deferred candidate use cases

| Use case | Why deferred | Reconsideration gate |
| --- | --- | --- |
| Knowledge refresh | Alert pilot must first prove the control plane and adoption | After Gate G5 |
| Engineering assistance | Depends on a trusted revisioned knowledge plane | After Gate G5 |
| SRE ticket planning | Higher operational consequence than alert recommendations | After Gate G5 |
| SRE mutation/action execution | Requires independent security, authorization, and audit approval | Separate post-pilot gate |

## Use-case decision record

| Decision | Options considered | Evidence | Owner/approvers | Date | Revisit condition |
| --- | --- | --- | --- | --- | --- |
| Select alert intelligence as the public sample | Knowledge refresh, engineering assistance, SRE planning, alert intelligence | Public cross-service evidence, synthetic personas, local-only side effects | Repository Owner | 2026-07-30 | Revisit after Gate G5 or if the demo cannot show evidence-backed value |

## Related documents

- [Vision](vision.md)
- [Users and jobs](users-and-jobs.md)
- [Metrics](metrics.md)
- [Launch plan](launch-plan.md)
- [Roadmap](roadmap.md)
