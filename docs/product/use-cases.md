# Product Use Cases

Status: draft template; candidate use cases require evidence and approval.

## Document control

| Field | Value |
| --- | --- |
| Product owner | `TBD` |
| Operational owner | `TBD` |
| Technical owner | `TBD` |
| Approvers | `TBD` |
| Last reviewed | `TBD` |

## Selection criteria

Score candidate use cases only after evidence is available.

| Criterion | Weight | Scoring rule | Evidence source |
| --- | --- | --- | --- |
| User/operational value | `TBD` | `TBD` | Interviews and baseline |
| Frequency | `TBD` | `TBD` | Alert history |
| Safety and reversibility | `TBD` | `TBD` | Risk review |
| Evidence availability | `TBD` | `TBD` | Service graph/runbook assessment |
| Evaluation feasibility | `TBD` | `TBD` | Replay dataset review |
| Delivery effort | `TBD` | `TBD` | Technical design |

## UC-01 — Alert intelligence

Status: candidate beachhead; approval `TBD`.

### User and outcome

- Primary user: SRE/on-call engineer (`TBD` validation).
- Trigger: a versioned, authenticated alert event from `sre-alert-agent`.
- Desired outcome: an evidence-backed recommendation delivered or held for
  review according to deterministic policy.
- Product value hypothesis: `TBD`.

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
| Unknown or incompatible event | Reject before workflow admission | `TBD` |
| Missing/stale evidence | Mark provisional and require review; do not silently suppress | `TBD` |
| Invalid model output or citation | Reject the decision and follow deterministic fallback | `TBD` |
| Retrieval/model timeout | Retry only when classified retryable, then review/fail safely | `TBD` |
| Ambiguous notification timeout | Reconcile using the durable idempotency receipt before retry | `TBD` |
| Telemetry unavailable | Continue according to business state; never use telemetry for recovery | Approved repository rule |

### Acceptance evidence

| Requirement | Measure/test | Threshold | Owner | Evidence |
| --- | --- | --- | --- | --- |
| Useful recommendations | `TBD` | `TBD` | `TBD` | `TBD` |
| Actionable-alert recall | `TBD` | `TBD` | `TBD` | `TBD` |
| Evidence validity | `TBD` | `TBD` | `TBD` | `TBD` |
| Review and delivery safety | Replay/resilience tests | `TBD` | `TBD` | `TBD` |
| Review-time improvement | Baseline versus pilot | `TBD` | `TBD` | `TBD` |

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
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

## Related documents

- [Vision](vision.md)
- [Users and jobs](users-and-jobs.md)
- [Metrics](metrics.md)
- [Launch plan](launch-plan.md)
- [Roadmap](roadmap.md)
