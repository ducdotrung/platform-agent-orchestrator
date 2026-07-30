# Product Metrics

Status: synthetic baseline and thresholds approved for the public hackathon
sample; not measured company results.

> All baseline values in this document are explicit planning assumptions for a
> deterministic 24-alert sample. They must never be quoted as observed user,
> operational, or production outcomes.

## Document control

| Field | Value |
| --- | --- |
| Product owner | Hackathon Product Lead (sample role) |
| Data/measurement owner | Evaluation Maintainer (sample role) |
| Operational owner | Demo Operator (sample role) |
| Approvers | Repository Owner (sample role) |
| Baseline window | Synthetic baseline v0.1: one fixed set of 24 alert scenarios |
| Pilot comparison window | Candidate replay against the same dataset version |
| Last reviewed | 2026-07-30 |

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
| Success | Preserve safety while reducing illustrative handling time | At least 90% actionable recall, 100% critical recall, 100% evidence validity, and at least 25% median handling-time reduction | One complete versioned replay | Replay report plus timed local demo | Hackathon Product Lead | Sample-approved |
| Stop/rollback | Safety, evidence, authorization, delivery, or durability failure | Any critical false negative, unsupported delivered claim, unauthorized/duplicate logical notification, or accepted-run loss | Any run | Replay, side-effect, audit, and run records | Demo Operator | Sample-approved |

## Synthetic baseline specification

The future D01 dataset will materialize these assumptions as sanitized fixtures.
Until that commit exists, this table is a planning specification, not a replay
result.

| Property | Sample value |
| --- | --- |
| Total scenarios | 24 |
| Ground-truth actionable | 10, including 4 critical cases |
| Ground-truth non-actionable | 14, including known noise |
| Allow-listed services | `front-end`, `orders`, `payment`, `shipping` |
| Evidence cases | available, missing, stale, and mismatched references |
| Adversarial cases | untrusted instruction-like alert/evidence text and unknown fields |
| Baseline handling model | Synthetic fully manual review |

## Baseline funnel

| Metric | Draft definition | Source | Owner | Window | Baseline |
| --- | --- | --- | --- | --- | --- |
| Alerts received | Count of scenarios admitted for manual handling | Synthetic baseline specification | Evaluation Maintainer | Baseline v0.1 | 24 |
| Alerts sent to Teams | Not applicable; the public sample has no Teams integration | Sample scope | Demo Operator | Baseline v0.1 | 0 / not applicable |
| Local notifications prepared | Count of recommendations prepared for local recording | Synthetic baseline specification | Evaluation Maintainer | Baseline v0.1 | 9 |
| Alerts dismissed/suppressed | Count treated as non-actionable, including one illustrative miss | Synthetic baseline specification | Evaluation Maintainer | Baseline v0.1 | 15 |
| Manual review rate | Reviewed in-scope scenarios / in-scope scenarios | Synthetic baseline specification | Evaluation Maintainer | Baseline v0.1 | 100% |
| Actionable decisions | Ground-truth actionable scenarios identified | Synthetic baseline specification | Evaluation Maintainer | Baseline v0.1 | 9 of 10 |
| Non-actionable decisions | Ground-truth non-actionable scenarios | Synthetic baseline specification | Evaluation Maintainer | Baseline v0.1 | 14 |
| Missed actionable alerts | Ground-truth actionable scenarios not identified | Synthetic baseline specification | Evaluation Maintainer | Baseline v0.1 | 1 of 10 |
| Median review time | Illustrative median from review start to decision | Synthetic workflow estimate | Hackathon Product Lead | Baseline v0.1 | 6 minutes |
| Alert-to-notification time | Illustrative median from receipt to local recommendation | Synthetic workflow estimate | Hackathon Product Lead | Baseline v0.1 | 8 minutes |
| Current model cost | Fully manual synthetic baseline | Sample scope | Hackathon Product Lead | Baseline v0.1 | USD 0.00 |

## Quality and safety

| Metric | Draft definition | Source | Owner | Target/gate |
| --- | --- | --- | --- | --- |
| Actionable-alert precision | Correct actionable predictions / all actionable predictions | Replay report | Evaluation Maintainer | At least 80% |
| Actionable-alert recall | Correct actionable predictions / all actually actionable cases | Replay report | Evaluation Maintainer | At least 90% overall; 100% critical |
| Severity-weighted false-negative rate | Missed actionable cases weighted critical=5, high=3, other=1 / total actionable weight | Replay report | Evaluation Maintainer | At most 5%; zero critical misses |
| Evidence validity | Factual claims supported by available referenced evidence / factual claims sampled | Replay/review | Platform/Safety Reviewer | 100% for delivered recommendations |
| Unsupported-claim rate | Unsupported factual claims / factual claims sampled | Replay/review | Platform/Safety Reviewer | 0% for delivered recommendations |
| Human-review agreement | Unedited sample approvals matching the rubric / reviewed cases | Replay report | Hackathon Product Lead | At least 80% |
| Unsafe proposal rate | Proposals violating approved sample safety policy / evaluated cases | Replay/review | Platform/Safety Reviewer | 0% |

## Product outcomes

| Metric | Draft definition | Source | Owner | Target/gate |
| --- | --- | --- | --- | --- |
| Recommendation acceptance | Accepted recommendations / reviewed recommendations | Replay rubric | Hackathon Product Lead | At least 80% |
| Edit/rejection/override rate | Each outcome / reviewed recommendations | Replay rubric | Hackathon Product Lead | Report only; no target until replay exists |
| Time saved per alert | Six-minute illustrative baseline minus timed demo handling | Timed local demo | Hackathon Product Lead | At least 1.5 minutes median (25%) |
| Weekly active pilot users | Not applicable to a local hackathon demonstration | None | Hackathon Product Lead | Not claimed |
| Cost per accepted recommendation | Model cost / accepted sample recommendations | Model usage plus replay | Evaluation Maintainer | At most USD 0.02 if a paid model is enabled; USD 0 with demo adapter |

## System outcomes

| Metric | Draft definition | Source | Owner | Target/gate |
| --- | --- | --- | --- | --- |
| End-to-end latency | Accepted event to terminal automation state, excluding human wait | Run records/metrics | Demo Operator | p95 at most 10 seconds locally |
| Queue delay | Outbox readiness to worker claim | Metrics | Demo Operator | p95 at most 2 seconds locally |
| Workflow recovery rate | Successfully recovered eligible interrupted runs / eligible interrupted runs | Run records | Demo Operator | 100% in resilience fixtures |
| Notification delivery rate | Accepted local receipts / attempted logical notifications | Side-effect records | Demo Operator | 100%, with zero duplicate logical notifications |
| Cost per completed task | Model cost / completed sample runs | Cost and run records | Evaluation Maintainer | At most USD 0.02 if a paid model is enabled |

## Reporting record

| Report/version | Baseline/candidate | Window | Dataset/release | Evidence location | Reviewer | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| Planning baseline v0.1 | Synthetic baseline | Fixed 24-scenario specification | Dataset not yet materialized; release identifier will be added by D05 | This document | Repository Owner | Approved for hackathon planning only |

## Related documents

- [Vision](vision.md)
- [Users and jobs](users-and-jobs.md)
- [Use cases](use-cases.md)
- [Launch plan](launch-plan.md)
- [Roadmap](roadmap.md)
