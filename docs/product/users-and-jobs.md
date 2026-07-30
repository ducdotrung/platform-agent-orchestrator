# Users and Jobs

Status: draft template; requires interviews and stakeholder validation.

## Document control

| Field | Value |
| --- | --- |
| Research owner | `TBD` |
| Product owner | `TBD` |
| Approvers | `TBD` |
| Interview window | `TBD` |
| Approved research location | `TBD` |
| Last reviewed | `TBD` |

## Research rules

- Obtain consent and follow company research and data-handling policy.
- Keep sensitive notes and recordings in the approved research location.
- Record evidence links here, not complete interview transcripts.
- Separate observed behavior from assumptions and proposed solutions.
- Include at least three representative perspectives before Gate G0.

## Candidate user groups

These groups come from the productization plan and are not validated personas.

| Candidate group | Proposed role in the workflow | Interview status | Evidence |
| --- | --- | --- | --- |
| SRE/on-call engineer | Reviews alerts and recommendations | `TBD` | `TBD` |
| Service owner | Supplies context and acts on recommendations | `TBD` | `TBD` |
| Product/operational owner | Owns launch value, policy, and rollback decisions | `TBD` | `TBD` |
| Security/platform stakeholder | Reviews identity, data, and operational controls | `TBD` | `TBD` |

## Interview register

Use participant codes rather than personal data where possible.

| Participant code | Role/team | Date | Research owner | Evidence link | Consent/classification |
| --- | --- | --- | --- | --- | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

## Interview guide

1. Walk through the last representative alert from receipt to resolution.
2. Which systems and people supplied context?
3. Which decisions required judgment, and which followed stable rules?
4. Where did time, handoffs, or missing evidence create delay?
5. What makes an alert recommendation useful or unsafe?
6. When must a human approve, edit, reject, or escalate the result?
7. Which failures would cause the team to stop using the product?
8. What outcome would demonstrate meaningful value?

## Current workflow

| Step | Actor | Input/system | Decision or action | Time/effort | Pain point | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

## Jobs to be done

Validate each statement and replace it when interview evidence disagrees.

| Situation | Job | Desired outcome | Trust/safety requirement | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| When an alert arrives | Determine whether it is actionable | Prioritize the right response quickly | No silent suppression of uncertain high-impact cases | `TBD` | `TBD` |
| When impact is unclear | Retrieve current service context | Understand affected dependencies and runbooks | Every claim links to bounded evidence | `TBD` | `TBD` |
| When a recommendation is proposed | Review or correct it | Make a controlled decision | Actor, reason, time, and decision are recorded | `TBD` | `TBD` |

## Synthesized findings

| Finding | Perspectives supporting it | Evidence IDs | Confidence | Product implication |
| --- | --- | --- | --- | --- |
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

## Open questions

- Which team and services form the launch group? `TBD`
- Which alert classes create the most value and risk? `TBD`
- What review experience should be reused? `TBD`
- What response time and evidence freshness do users need? `TBD`
- Which outcomes must always fall back to a human? `TBD`

## Related documents

- [Vision](vision.md)
- [Use cases](use-cases.md)
- [Metrics](metrics.md)
- [Launch plan](launch-plan.md)
- [Roadmap](roadmap.md)
