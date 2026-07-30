# Product Metrics

Status: draft metric dictionary; definitions, sources, windows, and thresholds
require owner approval.

## Document control

| Field | Value |
| --- | --- |
| Product owner | `TBD` |
| Data/measurement owner | `TBD` |
| Operational owner | `TBD` |
| Approvers | `TBD` |
| Baseline window | `TBD` |
| Pilot comparison window | `TBD` |
| Last reviewed | `TBD` |

## Measurement rules

- Define every metric before collecting the baseline.
- Name an authoritative data source and accountable owner.
- Keep business records, audit records, and sampled telemetry distinct.
- Segment only where privacy and sample size allow responsible interpretation.
- Record exclusions, missing data, and uncertainty with every report.
- Never use model confidence as measured correctness.

## Gate G0 success and rollback criteria

| Type | Criterion | Threshold | Window | Source | Owner | Approval |
| --- | --- | --- | --- | --- | --- | --- |
| Success | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |
| Stop/rollback | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

## Baseline funnel

| Metric | Draft definition | Source | Owner | Window | Baseline |
| --- | --- | --- | --- | --- | --- |
| Alerts received | Count of in-scope alert events accepted by the current alert system | `TBD` | `TBD` | `TBD` | `TBD` |
| Alerts sent to Teams | Count with an accepted delivery receipt | `TBD` | `TBD` | `TBD` | `TBD` |
| Alerts suppressed | Count ending in a defined suppression state | `TBD` | `TBD` | `TBD` | `TBD` |
| Manual review rate | Reviewed in-scope alerts / in-scope alerts | `TBD` | `TBD` | `TBD` | `TBD` |
| Actionable decisions | Count labeled actionable under the approved rubric | `TBD` | `TBD` | `TBD` | `TBD` |
| Non-actionable decisions | Count labeled non-actionable under the approved rubric | `TBD` | `TBD` | `TBD` | `TBD` |
| Missed actionable alerts | Actionable alerts not identified within the approved window | `TBD` | `TBD` | `TBD` | `TBD` |
| Median review time | Median from review start to recorded decision | `TBD` | `TBD` | `TBD` | `TBD` |
| Alert-to-notification time | Time from accepted source event to delivery receipt | `TBD` | `TBD` | `TBD` | `TBD` |
| Current model cost | Approved cost measure for the existing path | `TBD` | `TBD` | `TBD` | `TBD` |

## Quality and safety

| Metric | Draft definition | Source | Owner | Target/gate |
| --- | --- | --- | --- | --- |
| Actionable-alert precision | Correct actionable predictions / all actionable predictions | Replay plus reviewed outcomes | `TBD` | `TBD` |
| Actionable-alert recall | Correct actionable predictions / all actually actionable cases | Replay plus reviewed outcomes | `TBD` | `TBD` |
| Severity-weighted false-negative rate | Missed actionable cases weighted by approved severity weights | Replay plus incidents | `TBD` | `TBD` |
| Evidence validity | Factual claims supported by available referenced evidence / factual claims sampled | Replay/review | `TBD` | `TBD` |
| Unsupported-claim rate | Unsupported factual claims / factual claims sampled | Replay/review | `TBD` | `TBD` |
| Human-review agreement | Unedited approvals matching the reviewer rubric / reviewed cases | Business records | `TBD` | `TBD` |
| Unsafe proposal rate | Proposals violating approved safety policy / evaluated cases | Replay/review | `TBD` | `TBD` |

## Product outcomes

| Metric | Draft definition | Source | Owner | Target/gate |
| --- | --- | --- | --- | --- |
| Recommendation acceptance | Accepted recommendations / reviewed recommendations | Business records | `TBD` | `TBD` |
| Edit/rejection/override rate | Each outcome / reviewed recommendations | Business records | `TBD` | `TBD` |
| Time saved per alert | Comparable baseline handling time minus pilot handling time | Study and business records | `TBD` | `TBD` |
| Weekly active pilot users | Unique approved users completing a defined meaningful action | Business records | `TBD` | `TBD` |
| Cost per accepted recommendation | Allocated processing cost / accepted recommendations | Cost and business records | `TBD` | `TBD` |

## System outcomes

| Metric | Draft definition | Source | Owner | Target/gate |
| --- | --- | --- | --- | --- |
| End-to-end latency | Accepted event to terminal workflow state, by percentile | Business records/metrics | `TBD` | `TBD` |
| Queue delay | Outbox readiness to worker claim | Metrics | `TBD` | `TBD` |
| Workflow recovery rate | Successfully recovered eligible interrupted runs / eligible interrupted runs | Business records | `TBD` | `TBD` |
| Notification delivery rate | Accepted delivery receipts / attempted logical notifications | Side-effect records | `TBD` | `TBD` |
| Cost per completed task | Allocated model/infrastructure cost / completed runs | Cost and run records | `TBD` | `TBD` |

## Reporting record

| Report/version | Baseline/candidate | Window | Dataset/release | Evidence location | Reviewer | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

## Related documents

- [Vision](vision.md)
- [Users and jobs](users-and-jobs.md)
- [Use cases](use-cases.md)
- [Launch plan](launch-plan.md)
- [Roadmap](roadmap.md)
