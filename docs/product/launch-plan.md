# Alert Intelligence Launch Plan

Status: Gates G0 and G1 passed for the local public hackathon sample only; no
production launch is authorized.

> This plan governs a local reference demonstration using public Sock Shop
> metadata and synthetic alerts. It does not authorize company data, external
> notifications, credentials, or production traffic.

## Document control

| Field | Value |
| --- | --- |
| Product owner | Hackathon Product Lead (sample role) |
| Operational owner | Demo Operator (sample role) |
| Technical owner | Repository Maintainer (sample role) |
| Security reviewer | Platform/Safety Reviewer (sample role) |
| Pilot team owner | Hackathon Demo Team (synthetic) |
| Incident/rollback authority | Demo Operator (sample role) |
| Last reviewed | 2026-07-30 |

## Candidate launch scope

| Item | Value | Approval |
| --- | --- | --- |
| Workflow | Alert intelligence only | Sample-approved |
| Launch team | Synthetic Hackathon Demo Team | Sample-approved |
| Allow-listed services | Sock Shop `front-end`, `orders`, `payment`, `shipping` | Sample-approved |
| Environments | `public-demo` and local test only | Sample-approved |
| Source | Versioned synthetic fixtures shaped like the future `sre-alert-agent` contract | Sample-approved |
| External side effect | None; local in-memory notification receipt only | Sample-approved |
| Mutation tools | Disabled | Required repository rule |
| Observation window | One complete replay of the fixed dataset version | Sample-approved |

## Owners and communications

| Responsibility | Primary | Backup | Channel/location |
| --- | --- | --- | --- |
| Product decision | Hackathon Product Lead | Repository Owner | Repository issues/discussions |
| Operational response | Demo Operator | Repository Maintainer | Local demo terminal and repository issues |
| Deployment/rollback | Repository Maintainer | Demo Operator | Local environment only |
| Security/privacy | Platform/Safety Reviewer | Repository Owner | Repository security process |
| User support | Hackathon Product Lead | Repository Maintainer | Public README/issues |
| Metrics/reporting | Evaluation Maintainer | Hackathon Product Lead | Versioned local replay report |

## Rollout gates

| Gate | Entry criteria | Exit evidence | Decision owner | Status |
| --- | --- | --- | --- | --- |
| G0 — Scope | Product templates exist | Sample scope, roles, baseline assumptions, success, and rollback approved | Repository Owner | Passed for public sample on 2026-07-30 |
| G1 — Design | G0 passed | ADRs and read-only threat model approved | Repository Owner | Passed for public sample on 2026-07-30 |
| G2 — Local slice | G1 passed | Durable demo slice and recovery tests pass | Demo Operator | Runtime/PostgreSQL evidence passed; image/Compose smoke pending |
| G3 — Offline candidate | G2 passed | Public adapter contracts and replay thresholds pass | Hackathon Product Lead | Blocked by G2 |
| G4 — Shadow | G3 passed | Local shadow reliability, quality, latency, cost, and safety reviewed | Repository Owner | Blocked by G3 |
| G5 — Reviewed pilot | G4 passed | Judge/user demo with mandatory review meets sample criteria | Repository Owner | Blocked by G4 |
| G6 — Bounded auto-send | Out of scope for local-only hackathon sample | Separate future approval | Repository Owner | Deferred |

## Rollback and stop conditions

Define measurable triggers before shadow or pilot traffic begins.

| Trigger | Threshold/window | Detection source | Immediate action | Authority | Recovery evidence |
| --- | --- | --- | --- | --- | --- |
| Safety/false-negative regression | Any critical miss or overall recall below 90% in a complete replay | Replay report | Stop demonstration and revert candidate | Repository Owner | Corrected candidate passes the same dataset version |
| Unauthorized access or non-public data exposure | Any occurrence | Test/audit review | Stop demo, remove access, and follow repository security process | Repository Owner | Root cause fixed and negative tests pass |
| Duplicate or incorrect delivery | Any duplicate logical receipt or external notification | Side-effect records | Disable notification path | Demo Operator | Replay/resilience tests pass with local receipts only |
| Reliability/latency breach | Accepted-run loss, failed recovery, or local p95 automation latency above 15 seconds | Run records/metrics | Stop gate promotion and diagnose | Demo Operator | Recovery is 100% and p95 returns to at most 10 seconds |
| Cost/budget breach | More than USD 0.02 per completed task if a paid model is enabled | Usage report | Switch to demo adapter or stop model calls | Hackathon Product Lead | Cost report meets threshold |
| Evidence/trust breach | Any delivered unsupported claim or evidence validity below 100% | Replay/review | Stop delivery and require review for all cases | Platform/Safety Reviewer | Evidence tests and replay pass |

## Readiness checklist

- [x] Sample roles and backups are assigned for the local demonstration.
- [x] Sample scope, synthetic perspectives, success criteria, and rollback
  criteria are approved for the hackathon.
- [x] Data classification, retention, and deletion ownership are approved for
  the public sample.
- [x] Authentication, authorization, replay protection, and audit are tested.
- [ ] Replay evaluation and release gates meet approved thresholds.
- [ ] Dashboards, alerts, support paths, and runbooks are exercised.
- [ ] Restore, worker-recovery, duplicate-delivery, and rollback exercises pass.
- [ ] Pilot users have training, documentation, and a feedback channel.
- [ ] No mutation credentials or tools are enabled.

## Launch decision record

| Gate/date | Evidence reviewed | Risks/exceptions | Decision | Decision owner/approvers | Follow-up |
| --- | --- | --- | --- | --- | --- |
| G0 / 2026-07-30 | Public Sock Shop scope, synthetic perspectives, 24-case baseline specification, sample thresholds, and local-only side effects | No real interviews or measured production baseline; dataset fixtures are deferred to D01 | Pass for hackathon sample only | Repository Owner (sample role) | Begin Track A ADRs; repeat G0 with real evidence before company reuse |
| G1 / 2026-07-30 | ADR-0001 through ADR-0006 plus read-only data-flow, classification, STRIDE/AI/MCP threat review | Implementation controls remain unverified until B/C/D tasks; local host, bearer-token, single-database-host, and no-backup residual risks accepted only for sample | Pass for hackathon sample only | Repository Owner and Platform/Safety Reviewer (sample roles) | Begin B01; keep external delivery, mutation, company data, and public exposure disabled |

## Related documents

- [Vision](vision.md)
- [Users and jobs](users-and-jobs.md)
- [Use cases](use-cases.md)
- [Metrics](metrics.md)
- [Roadmap](roadmap.md)
- [Threat model](../security/read-only-pilot-threat-model.md)
- [Execution backlog](../production-productization-review.md)
