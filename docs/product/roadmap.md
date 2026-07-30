# Product Roadmap

Status: outcome roadmap approved for the public hackathon sample; company reuse
requires replanning.

## Document control

| Field | Value |
| --- | --- |
| Product owner | Hackathon Product Lead (sample role) |
| Technical owner | Repository Maintainer (sample role) |
| Operational owner | Demo Operator (sample role) |
| Approvers | Repository Owner (sample role) |
| Planning horizon | Gate-based through the public hackathon demonstration |
| Review cadence | At every gate |
| Last reviewed | 2026-07-30 |

## Roadmap rules

- Prioritize measurable outcomes and risk reduction, not feature count.
- Gate real-system integration on security, data, and evaluation readiness.
- Keep domain work in its owning repository and link cross-repository issues.
- Do not schedule expansion until the alert pilot demonstrates adoption and
  reliable operation.
- Revisit priorities when evidence invalidates a problem or value hypothesis.

## Now — Validate scope and design

Target gates: G0 and G1. Dates are intentionally gate-based.

| Outcome | Evidence of completion | Owner | Dependencies | Status |
| --- | --- | --- | --- | --- |
| Define the sample alert-review problem and demo perspectives | Three explicitly synthetic perspectives and a sample current workflow | Hackathon Product Lead | Public Sock Shop scope | Complete for sample |
| Establish synthetic baseline, success, and rollback measures | Approved metric dictionary, fixed scenario specification, roles, and thresholds | Evaluation Maintainer | Sample assumptions | Complete for sample |
| Resolve implementation architecture decisions | Approved runtime, delivery, persistence, identity, scope, deployment, and adapter ADRs | Repository Maintainer | G0 | A03-A07 accepted |
| Approve public-demo data and threat model | Data flows, classification, retention, and threats reviewed | Platform/Safety Reviewer | Architecture ADRs | Complete for sample; Gate G1 passed |

## Next — Prove the read-only alert slice

Target gates: G2 and G3. Start only after G1.

| Outcome | Evidence of completion | Owner | Dependencies | Status |
| --- | --- | --- | --- | --- |
| Prove durable local execution | Admission, worker, restart/resume, and idempotency tests pass with demo adapters | Repository Maintainer | G1 | Runtime and PostgreSQL evidence complete; image/Compose smoke pending |
| Connect bounded public adapters | Consumer-driven Sock Shop graph contracts pass without copying domain logic | Repository Maintainer | Companion toolkit contract | Blocked by G2 |
| Establish reproducible evaluation | Versioned 24-case replay report meets approved sample thresholds | Evaluation Maintainer | D01 fixtures | Dataset/rubric complete; replay runner awaits C05 |
| Establish minimum demo operations | Local container/startup, metrics, runbooks, recovery, and rollback are exercised | Demo Operator | G2 implementation | Blocked by G2 |

## Later — Shadow, pilot, and learn

Target gates: G4-G5. G6 auto-send is deferred for the local-only sample.

| Outcome | Evidence of completion | Owner | Dependencies | Status |
| --- | --- | --- | --- | --- |
| Validate safely in local shadow mode | No notification receipt; measured quality, reliability, latency, and cost reviewed | Demo Operator | G3 | Blocked by G3 |
| Validate the judge/user demonstration with mandatory review | Sample demo meets approved value, trust, and reliability criteria | Hackathon Product Lead | G4 | Blocked by G4 |
| Keep auto-send disabled | No external delivery capability exists in the public sample | Platform/Safety Reviewer | Sample scope | Deferred |
| Prioritize or reject further public-demo expansion | Roadmap decision is backed by hackathon results without claiming company adoption | Repository Owner | G5 results | Blocked by G5 |

## Deferred expansion

- Knowledge refresh with real Bitbucket events and atomic publication.
- Engineering assistance over the trusted revisioned knowledge plane.
- Read-only SRE ticket planning.
- Human-approved allow-listed SRE actions after a separate security review.
- Broad tenancy, advanced memory, or generic workflow-building capabilities.

## Cross-repository dependency register

| Capability/change | Owning repository/team | Contract/issue | Required by | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Alert event production and policy | Local fixture in this repository | Future versioned event contract | G2 | Repository Maintainer | Synthetic fixture implemented |
| Company alert event production | `sre-alert-agent` | Explicitly excluded from public sample | Company reuse | Future company owner | Deferred |
| Teams notification delivery | `sre-alert-agent` | Explicitly excluded from public sample | Company reuse | Future company owner | Deferred |
| Read-only public service evidence | `service-graph-toolkit` | Sock Shop inventory and local MCP contract | G3 | Companion repository maintainer | Public sample available |
| Bounded SRE knowledge | `sre-skills` | Deferred for alert pilot | Later | Future owner | Deferred |
| User-facing wiki/UI | `code-atlas-workbench` | Deferred for alert pilot | Later | Future owner | Deferred |

## Roadmap decision record

| Date | Decision | User/problem evidence | Trade-offs | Expected metric effect | Owner/approvers | Revisit condition |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-30 | Use Sock Shop checkout services and a synthetic 24-alert baseline for the public sample | Public companion inventory and explicitly synthetic perspectives | Reproducible and safe, but not real user validation | Establish hackathon evaluation targets only | Repository Owner | Repeat discovery before company reuse or if the sample cannot demonstrate value |

## Related documents

- [Vision](vision.md)
- [Users and jobs](users-and-jobs.md)
- [Use cases](use-cases.md)
- [Metrics](metrics.md)
- [Launch plan](launch-plan.md)
- [Execution backlog](../production-productization-review.md)
