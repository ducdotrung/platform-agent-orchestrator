# Product Vision

Status: draft template; requires stakeholder validation.

## Document control

| Field | Value |
| --- | --- |
| Product owner | `TBD` |
| Operational owner | `TBD` |
| Executive sponsor | `TBD` |
| Approvers | `TBD` |
| Last reviewed | `TBD` |
| Next review | `TBD` |

## Candidate vision

Provide a governed internal platform that converts operational and engineering
events into evidence-backed decisions and bounded actions, with human control
wherever risk or uncertainty requires it.

Approval status: `TBD`.

## Problem statement

Candidate beachhead problem: on-call engineers receive alerts and must determine
impact, retrieve service context, decide urgency, and prepare a response. The
current workflow, pain points, frequency, and cost must be validated through
interviews and baseline data before this statement is approved.

| Question | Evidence-backed answer |
| --- | --- |
| Who experiences the problem? | `TBD` |
| What do they do today? | `TBD` |
| Where is time or trust lost? | `TBD` |
| How frequently does it occur? | `TBD` |
| What is the operational impact? | `TBD` |
| Why solve it now? | `TBD` |

## Candidate first product

Alert intelligence is the proposed first product. It would accept a versioned
alert event produced by `sre-alert-agent`, retrieve bounded evidence, make a
structured impact assessment, request review when required, and return a
deduplicated notification through the alert system's existing delivery
capability.

Pilot approval: `TBD`.

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

- One launch team and an explicitly allow-listed set of services: `TBD`.
- Alert intelligence only.
- Read-only retrieval and governed notification delivery.
- Mandatory review policy: `TBD`.
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
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

## Open decisions

| Decision | Owner | Due date | Evidence needed | Status |
| --- | --- | --- | --- | --- |
| Approve the beachhead problem and first product | `TBD` | `TBD` | Interviews and baseline | `TBD` |
| Name product, operational, and launch owners | `TBD` | `TBD` | Responsibility agreement | `TBD` |
| Approve pilot scope and non-goals | `TBD` | `TBD` | Risk and value review | `TBD` |

## Related documents

- [Users and jobs](users-and-jobs.md)
- [Use cases](use-cases.md)
- [Metrics](metrics.md)
- [Launch plan](launch-plan.md)
- [Roadmap](roadmap.md)
- [Productization review](../production-productization-review.md)
