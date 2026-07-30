# Product Roadmap

Status: draft outcome roadmap; dates and commitments require owner approval.

## Document control

| Field | Value |
| --- | --- |
| Product owner | `TBD` |
| Technical owner | `TBD` |
| Operational owner | `TBD` |
| Approvers | `TBD` |
| Planning horizon | `TBD` |
| Review cadence | `TBD` |
| Last reviewed | `TBD` |

## Roadmap rules

- Prioritize measurable outcomes and risk reduction, not feature count.
- Gate real-system integration on security, data, and evaluation readiness.
- Keep domain work in its owning repository and link cross-repository issues.
- Do not schedule expansion until the alert pilot demonstrates adoption and
  reliable operation.
- Revisit priorities when evidence invalidates a problem or value hypothesis.

## Now — Validate scope and design

Target gates: G0 and G1. Dates: `TBD`.

| Outcome | Evidence of completion | Owner | Dependencies | Status |
| --- | --- | --- | --- | --- |
| Validate the alert-review problem and launch users | Three or more representative perspectives and current-workflow evidence | `TBD` | Stakeholder access | `TBD` |
| Establish baseline, success, and rollback measures | Approved metric dictionary, sources, owners, windows, and thresholds | `TBD` | Data access | `TBD` |
| Resolve production architecture decisions | Approved runtime, delivery, persistence, identity, tenancy, deployment, and adapter ADRs | `TBD` | Platform/security input | `TBD` |
| Approve read-only data and threat model | Data flows, classification, retention, and threats reviewed | `TBD` | Security/privacy input | `TBD` |

## Next — Prove the read-only alert slice

Target gates: G2 and G3. Dates: `TBD`.

| Outcome | Evidence of completion | Owner | Dependencies | Status |
| --- | --- | --- | --- | --- |
| Prove durable local execution | Admission, worker, restart/resume, and idempotency tests pass with demo adapters | `TBD` | G1 | `TBD` |
| Connect bounded real adapters | Consumer-driven contracts pass without copying domain logic | `TBD` | External owners | `TBD` |
| Establish reproducible evaluation | Versioned replay report meets approved quality and safety thresholds | `TBD` | Protected dataset | `TBD` |
| Establish minimum operations | Deployment, dashboards, alerts, runbooks, recovery, and rollback are exercised | `TBD` | Platform support | `TBD` |

## Later — Shadow, pilot, and learn

Target gates: G4-G6. Dates: `TBD`.

| Outcome | Evidence of completion | Owner | Dependencies | Status |
| --- | --- | --- | --- | --- |
| Validate safely in shadow mode | No user-visible delivery; measured quality, reliability, latency, and cost reviewed | `TBD` | G3 | `TBD` |
| Validate adoption with mandatory review | One-team pilot meets approved value, trust, and reliability criteria | `TBD` | G4 | `TBD` |
| Consider bounded auto-send | Only approved low-risk cases canary successfully | `TBD` | Explicit G5 decision | `TBD` |
| Prioritize or reject platform expansion | Roadmap decision is backed by pilot evidence | `TBD` | G5 results | `TBD` |

## Deferred expansion

- Knowledge refresh with real Bitbucket events and atomic publication.
- Engineering assistance over the trusted revisioned knowledge plane.
- Read-only SRE ticket planning.
- Human-approved allow-listed SRE actions after a separate security review.
- Broad tenancy, advanced memory, or generic workflow-building capabilities.

## Cross-repository dependency register

| Capability/change | Owning repository/team | Contract/issue | Required by | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Alert event production and policy | `sre-alert-agent` | `TBD` | G3 | `TBD` | `TBD` |
| Teams notification delivery | `sre-alert-agent` | `TBD` | G3 | `TBD` | `TBD` |
| Read-only service/runbook evidence | `service-graph-toolkit` | `TBD` | G3 | `TBD` | `TBD` |
| Bounded SRE knowledge | `sre-skills` | Deferred for alert pilot | Later | `TBD` | Deferred |
| User-facing wiki/UI | `code-atlas-workbench` | Deferred for alert pilot | Later | `TBD` | Deferred |

## Roadmap decision record

| Date | Decision | User/problem evidence | Trade-offs | Expected metric effect | Owner/approvers | Revisit condition |
| --- | --- | --- | --- | --- | --- | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

## Related documents

- [Vision](vision.md)
- [Users and jobs](users-and-jobs.md)
- [Use cases](use-cases.md)
- [Metrics](metrics.md)
- [Launch plan](launch-plan.md)
- [Execution backlog](../production-productization-review.md)
