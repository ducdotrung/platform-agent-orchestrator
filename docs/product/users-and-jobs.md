# Users and Jobs

Status: synthetic perspectives approved for the public hackathon sample.

> No people were interviewed for this sample. The perspectives below are demo
> personas used to exercise product reasoning; they are not user-research
> evidence and must not be presented as company validation.

## Document control

| Field | Value |
| --- | --- |
| Research owner | Hackathon Product Lead (sample role) |
| Product owner | Hackathon Product Lead (sample role) |
| Approvers | Repository Owner (sample role) |
| Interview window | Not applicable; no interviews performed |
| Approved research location | This public synthetic document |
| Last reviewed | 2026-07-30 |

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
| SRE/on-call engineer | Reviews alerts and recommendations | Synthetic sample | SP-01 |
| Orders service owner | Supplies checkout context and checks dependency impact | Synthetic sample | SP-02 |
| Platform/safety reviewer | Reviews evidence, side effects, data boundaries, and rollback | Synthetic sample | SP-03 |
| Product/operational owner | Owns demo value, policy, and stop decisions | Combined sample role | SP-01 through SP-03 |

## Interview register

Use participant codes rather than personal data where possible.

| Participant code | Role/team | Date | Research owner | Evidence link | Consent/classification |
| --- | --- | --- | --- | --- | --- |
| No interviews | Public hackathon sample | 2026-07-30 | Hackathon Product Lead | This document | Public/synthetic |

## Synthetic perspective register

| ID | Perspective | Sample need | Trust or safety concern | Validation status |
| --- | --- | --- | --- | --- |
| SP-01 | Sock Shop on-call engineer | Identify whether checkout alerts are actionable without manually tracing every dependency | Critical or uncertain alerts must not be silently suppressed | Synthetic only |
| SP-02 | Orders service owner | See whether an orders symptom is supported by payment or shipping dependency evidence | Recommendations must distinguish declared/static evidence from runtime truth | Synthetic only |
| SP-03 | Platform/safety reviewer | Demonstrate controlled retries, review, redaction, and local-only side effects | No credentials, private data, mutation tools, or external notifications | Synthetic only |

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
| 1 | Synthetic on-call engineer | Local alert fixture | Identify service, severity, count, users, and environment | 2 minutes | Context is not yet connected to dependencies | SP-01 |
| 2 | Synthetic on-call engineer | Sock Shop graph | Inspect `front-end`, `orders`, `payment`, and `shipping` relationships | 2 minutes | Manual evidence navigation | SP-01, SP-02 |
| 3 | Synthetic service owner | Source/graph evidence | Decide whether the alert is actionable and estimate impact | 1 minute | Static evidence can be mistaken for runtime truth | SP-02 |
| 4 | Synthetic on-call engineer | Manual notes | Prepare and review a recommendation | 1 minute | Claims and evidence can drift apart | SP-01 |
| 5 | Synthetic on-call engineer | Local demo notifier | Record the outcome | 2 minutes | Duplicate delivery must be controlled | SP-01, SP-03 |

## Jobs to be done

Validate each statement and replace it when interview evidence disagrees.

| Situation | Job | Desired outcome | Trust/safety requirement | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| When an alert arrives | Determine whether it is actionable | Prioritize the right sample response quickly | No silent suppression of uncertain high-impact cases | SP-01 | Accepted sample hypothesis |
| When impact is unclear | Retrieve current service context | Understand declared checkout dependencies | Every claim links to bounded evidence and states evidence limits | SP-02 | Accepted sample hypothesis |
| When a recommendation is proposed | Review or correct it | Make a controlled local decision | Actor, reason, time, and decision are recorded | SP-01, SP-03 | Accepted sample hypothesis |

## Synthesized findings

| Finding | Perspectives supporting it | Evidence IDs | Confidence | Product implication |
| --- | --- | --- | --- | --- |
| The hackathon story needs a visible cross-service path | SP-01, SP-02 | E-01, SP-01, SP-02 | Sample assumption | Focus on `front-end` -> `orders` -> `payment`/`shipping` |
| Trust is more important than autonomous action in the demo | SP-01, SP-03 | SP-01, SP-03 | Sample assumption | Require review and keep notifications local |
| Evidence types must not be overstated | SP-02, SP-03 | E-01, E-02, SP-02 | Supported by companion docs | Label inventory/static-code evidence as non-runtime evidence |

## Open questions

- Launch group: synthetic Hackathon Demo Team; `front-end`, `orders`, `payment`,
  and `shipping`.
- Sample alert classes: checkout error spikes, payment failures, shipping
  failures/latency, known noise, and missing/stale evidence.
- Review experience: local CLI/API representation for the hackathon; company UI
  selection is deferred.
- Sample target: ten-second p95 automation latency excluding human wait;
  evidence is tied to the selected graph revision.
- Human fallback: critical, provisional, low-confidence, missing/stale evidence,
  and policy-ambiguous outcomes.

## Related documents

- [Vision](vision.md)
- [Use cases](use-cases.md)
- [Metrics](metrics.md)
- [Launch plan](launch-plan.md)
- [Roadmap](roadmap.md)
