# Product Vision

Status: sample-approved for the public hackathon; not validated for company use.

> This is a synthetic product brief for a public reference implementation. Role
> names, baseline values, and thresholds are demo assumptions, not evidence
> about a real team. Company adoption requires a new discovery and approval
> cycle.

## Document control

| Field | Value |
| --- | --- |
| Product owner | Hackathon Product Lead (sample role) |
| Operational owner | Demo Operator (sample role) |
| Executive sponsor | Not applicable to the public sample |
| Approvers | Repository Owner and Hackathon Product Lead (sample roles) |
| Last reviewed | 2026-07-30 |
| Next review | Before reuse with company services |

## Candidate vision

Provide a governed internal platform that converts operational and engineering
events into evidence-backed decisions and bounded actions, with human control
wherever risk or uncertainty requires it.

Approval status: approved for the public hackathon sample only.

## Problem statement

Candidate beachhead problem: on-call engineers receive alerts and must determine
impact, retrieve service context, decide urgency, and prepare a response. The
current workflow, pain points, frequency, and cost must be validated through
interviews and baseline data before this statement is approved.

| Question | Evidence-backed answer |
| --- | --- |
| Who experiences the problem? | A synthetic on-call engineer supporting the Sock Shop checkout path |
| What do they do today? | Review an alert, inspect service relationships and code, decide impact, and prepare a notification manually |
| Where is time or trust lost? | Moving between alert details and dependency evidence, then checking whether a recommendation is supported |
| How frequently does it occur? | The demo baseline models 24 alerts in one versioned scenario set; this is not an observed rate |
| What is the operational impact? | A missed checkout-path alert can hide impact across orders, payment, or shipping in the sample scenario |
| Why solve it now? | Demonstrate a governed alert-intelligence vertical slice using public, reproducible evidence |

## Candidate first product

Alert intelligence is the proposed first product. It would accept a versioned
alert event produced by `sre-alert-agent`, retrieve bounded evidence, make a
structured impact assessment, request review when required, and return a
deduplicated notification through the alert system's existing delivery
capability.

Pilot approval: approved as a local public demonstration; no production launch
or company integration is authorized.

## Product principles

- Evidence is required for factual claims.
- Deterministic code owns parsing, validation, routing, authorization, policy,
  and side-effect control.
- An LLM is used only for semantic judgment that has an explicit evaluation.
- Risky or uncertain outcomes require human review.
- External side effects are idempotent and auditable.
- Domain capabilities remain in their owning repositories.
- Telemetry is not workflow state or an audit ledger.

## Candidate scope

### In scope for the first pilot

- One synthetic Hackathon Demo Team.
- Allow-listed Sock Shop services: `front-end`, `orders`, `payment`, and
  `shipping`.
- Alert intelligence only.
- Read-only retrieval from the companion service graph.
- Local in-memory notification only; no Teams or external delivery.
- Mandatory review for provisional, missing-evidence, low-confidence, and
  critical cases.
- Shadow and rollback controls.

### Out of scope

- Autonomous remediation or mutation tools.
- Productionizing the other three reference workflows.
- Generic agent or plugin builders.
- Broad multi-tenancy.
- Self-modifying prompts, policies, models, or tools.
- Long-term memory without an evaluated requirement.

## Evidence register

Do not copy sensitive interview notes or raw alert data into this repository.
Link to an approved location and record only the minimum metadata needed here.

| ID | Claim supported | Source/location | Owner | Classification | Collected on |
| --- | --- | --- | --- | --- | --- |
| E-01 | Sock Shop contains seven services and the checkout dependency edges used by the demo | `service-graph-toolkit/projects/sock-shop/inventory.yaml` | Service Graph Toolkit maintainers | Public | 2026-07-30 |
| E-02 | The companion toolkit exposes local read-only Sock Shop service and code evidence | `service-graph-toolkit/docs/MCP-DEMO.md` | Service Graph Toolkit maintainers | Public | 2026-07-30 |
| E-03 | The current orchestrator has deterministic alert classification, evidence enrichment, review, and demo notification nodes | `src/platform_agent_orchestrator/workflows/alert.py` | Repository Owner | Public | 2026-07-30 |
| E-04 | Three synthetic user perspectives define the hackathon story | [Users and jobs](users-and-jobs.md) | Hackathon Product Lead | Public/synthetic | 2026-07-30 |

## Open decisions

| Decision | Owner | Due date | Evidence needed | Status |
| --- | --- | --- | --- | --- |
| Approve the beachhead problem and first product | Repository Owner | 2026-07-30 | Public sample and synthetic baseline | Approved for hackathon sample |
| Name product, operational, and launch owners | Repository Owner | 2026-07-30 | Sample role assignment | Approved for hackathon sample |
| Approve pilot scope and non-goals | Repository Owner | 2026-07-30 | Public-data and safety review | Approved for hackathon sample |
| Replace synthetic discovery before company use | Future company Product Owner | Before company implementation | Interviews and measured baseline | Required |

## Related documents

- [Users and jobs](users-and-jobs.md)
- [Use cases](use-cases.md)
- [Metrics](metrics.md)
- [Launch plan](launch-plan.md)
- [Roadmap](roadmap.md)
- [Productization review](../production-productization-review.md)
