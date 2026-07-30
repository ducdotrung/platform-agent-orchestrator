# Read-Only Public Pilot Threat Model and Data Classification

- Status: accepted for Gate G1 of the public hackathon sample
- Review date: 2026-07-30
- System owner: Repository Owner (sample role)
- Security reviewer: Platform/Safety Reviewer (sample role)
- Scope: local Sock Shop alert-review sample through Gate G3
- Method: data-flow/trust-boundary review using STRIDE plus generative-AI and
  MCP-specific abuse cases
- Depends on: ADR-0001 through ADR-0006

## Decision

The design gate passes for the local public sample with the controls and
accepted limitations in this document. This approval does not authorize company
data, production traffic, external notification, a real model provider, public
network exposure, remote MCP, or mutation tools.

The central security rule is:

> Data classification and data trust are independent. Public or synthetic
> content can still be malicious. Event, evidence, model, and tool content is
> always treated as untrusted data and never as authorization, policy, routing,
> or executable instruction.

Company reuse requires a new threat model with actual deployment, identity,
data, legal/privacy, provider, incident-response, and retention owners.

## System and security objectives

The sample accepts a versioned synthetic alert, durably queues one alert-review
workflow, retrieves bounded public Sock Shop evidence, produces a structured
decision, may interrupt for human review, and records a local receipt. It does
not operate a service or send a user-visible notification.

Security objectives, in priority order:

1. prevent credentials, private/company data, and raw provider traffic from
   entering workflow state, checkpoints, audit, telemetry, or Git;
2. prevent unauthenticated, unauthorized, replayed, or cross-scope mutations;
3. keep untrusted content from changing tools, policy, prompts, routes,
   destinations, or approval state;
4. preserve accepted events, checkpoint recovery, approval history, and audit
   integrity across process failure;
5. prevent duplicate or ambiguous logical side effects;
6. bound CPU, memory, storage, subprocess, dependency, and telemetry exposure;
7. fail closed or require review when evidence, identity, policy, dependency,
   or model output is missing or invalid.

Availability of the local workstation and retention after host/volume loss are
not security guarantees of the sample.

## Scope

### In scope

- loopback FastAPI ingress and local fixture token/signature profiles;
- deterministic authentication, authorization, validation, and routing;
- PostgreSQL application records and durable jobs;
- separate PostgreSQL LangGraph checkpoints;
- one worker, deterministic local reasoning, and local receipt-only notifier;
- optional pinned read-only `service-graph-toolkit` stdio child for public Sock
  Shop metadata;
- approval, operator replay, audit, retention, logs, metrics, and optional
  content-disabled telemetry;
- build inputs, Compose configuration, local secret files, and named volumes.

### Out of scope and prohibited

- real Sentry/company alerts, private repositories, source corpora, runbooks,
  customer/user data, employee data, or company service metadata;
- Teams, Jira, email, chat, ticket, paging, or other external delivery;
- arbitrary workflow/tool selection, shell execution, source indexing,
  publication, remediation, or any mutation tool;
- public ingress, remote MCP, production OAuth/OIDC, company SSO, Kubernetes,
  cloud secrets, backup, or disaster recovery;
- real model-provider credentials or prompts containing non-public data;
- autonomous prompt/policy/model/tool changes and bounded auto-send.

Attempting to enable an out-of-scope capability is a design change, not
configuration.

## Actors

| Actor | Trust assumption | Allowed action |
| --- | --- | --- |
| Synthetic producer service | Possesses a short-lived local service identity; request content remains untrusted | Submit allow-listed synthetic alert events |
| Demo reviewer | Local human fixture identity; may still make mistakes | Read same-scope runs/approvals, decide one bound approval, provide feedback |
| Demo operator | Local human fixture identity with bounded replay privilege | Inspect and replay eligible closed failures with reason |
| Safety reviewer | Separate sample role | Review/release quarantine when explicitly permitted |
| Repository maintainer | Controls code, policy, locks, and local deployment | Build/configure the approved sample |
| Local host process | Not automatically trusted | Must not access stdio MCP, secret files, or Docker control without OS permission |
| Public evidence author | Unknown/untrusted | Supplies authored public metadata only |
| Dependency/package maintainer | External supply-chain actor | Supplies pinned build/runtime dependencies |
| Network attacker | Limited by loopback-only design | No authorized action |
| Malicious event/evidence author | Can craft public-looking content | No control-plane authority |

The sample assumes the workstation operator and host kernel are not already
fully compromised. A host administrator can bypass container, process, file,
and database controls; that residual risk is accepted only for the local demo.

## Trust boundaries and data flow

```text
TB1: local human/service identity boundary

  demo-token / demo-event / reviewer
                |
                | JWT or signed request + bounded JSON
                v
        +-----------------+
        | API             |
        | authn/authz     |
        | validate/route  |
        +--------+--------+
                 |
                 | TB2: transactional persistence boundary
                 v
       +---------------------+
       | application DB      |
       | event/run/job/audit |
       +----------+----------+
                  |
                  | fenced job lease
                  v
        +-------------------+
        | worker            |
        | graph/policy      |
        +---+-----------+---+
            |           |
            |           | TB4: external/read adapter boundary
            |           +----> deterministic adapters
            |           +----> optional pinned stdio MCP child
            |
            | TB3: saver-owned persistence boundary
            v
       +---------------------+
       | checkpoint DB       |
       | saver-owned objects |
       +---------------------+

TB5: optional telemetry export boundary (content disabled)
TB6: build/configuration/supply-chain boundary
```

### Flow inventory

| Flow | Data | Source -> destination | Boundary controls | Failure behavior |
| --- | --- | --- | --- | --- |
| F01 | Local JWT/public verification key | Fixture command -> API | Loopback, asymmetric signature, issuer/audience/lifetime validation | `401`; no mutation |
| F02 | Signed synthetic alert | Producer -> API | Auth profile, digest/signature/nonce or JWT, size/schema/source/scope limits | Reject before run |
| F03 | Canonical event/run/job/audit | API -> application DB | One transaction, fingerprint, idempotency, least-privilege role | Roll back together |
| F04 | Job/lease/run state | Worker <-> application DB | `SKIP LOCKED`, lease token fence, bounded transactions | Retry/reclaim |
| F05 | Graph checkpoint | Worker <-> checkpoint DB | Separate role/database, strict msgpack, stable thread ID | Resume/reconcile |
| F06 | Public evidence request/result | Worker <-> local fixture or stdio MCP | Fixed project/tool, read-only checkout, schema/size/path/time limits | Review/fail closed |
| F07 | Structured reasoning | Graph -> deterministic reasoner | Typed bounded evidence; no tool/policy authority | Review/fallback |
| F08 | Local logical notification | Worker -> receipt adapter | Durable side-effect reservation, stable key/hash | Reconcile; no external send |
| F09 | Approval decision | Reviewer -> API -> DB | Human identity, same scope, action hash/version/expiry/idempotency | Reject stale/replayed |
| F10 | Operator replay | Operator -> API -> DB | Explicit permission/reason/idempotency; linked history | No automatic/bulk replay |
| F11 | Bounded telemetry | Process -> optional backend | Off by default, content disabled, redaction/sampling | Never changes workflow |
| F12 | Images/config/secrets | Maintainer -> Compose/processes | Pinned inputs, minimum mounts, non-root/read-only runtime | Fail startup/readiness |

## Data classification

Classification answers disclosure impact. The independent `Trust` column
answers whether content may control behavior.

| Class | Meaning | Examples | Git allowed? | Application/checkpoint allowed? |
| --- | --- | --- | --- | --- |
| C0 Public sample | Intentionally public, sanitized, redistributable sample data | Sock Shop inventory locators, synthetic fixtures, schemas, public docs | Yes after license/provenance review | Yes, bounded |
| C1 Local operational | Non-secret runtime metadata not intended as repository content | Run/job IDs, states, approvals, reasons, audit, local receipts, policy versions | No, except sanitized fixtures/reports | Yes according to authority/retention |
| C2 Secret/security | Material enabling authentication, database access, signing, or protected provider use | Private keys, passwords, bearer tokens, signatures, DSNs with credentials | Never | Never in business/checkpoint/audit state |
| C3 Prohibited | Data outside sample authorization | Company alerts/source/runbooks, customer/employee/PII, private endpoints, raw model/tool traffic, full source corpora | Never | Never |

| Dataset | Class | Trust | Authoritative location | Retention/action |
| --- | --- | --- | --- | --- |
| Synthetic event fixture | C0 | Untrusted | Versioned Git fixture | Repository history |
| Accepted event payload | C0 | Untrusted | Application DB | Tombstone 30 days after terminal run |
| Event fingerprint/identity | C1 | Deterministic | Application DB | 180 days |
| Run/job/attempt summary | C1 | Deterministic application state | Application DB | 180 days |
| Graph checkpoint | C0/C1 bounded state | Contains untrusted data | Checkpoint DB | Delete thread after 30 days |
| Evidence reference | C0 | Untrusted source, validated shape | Checkpoint/run summary | With owning run/checkpoint |
| Raw MCP response | C0 | Untrusted | Adapter memory only | Discard after bounded conversion |
| Decision/recommendation | C1 | Untrusted semantic output until policy/review | Checkpoint plus bounded run summary | 30/180-day policy |
| Approval/reason | C1 | Trusted actor decision, bounded text still untrusted for rendering | Application DB | 180 days |
| Local side-effect receipt | C1 | Adapter output validated | Application DB | 180 days |
| Audit event | C1 | Authoritative append-only application record | Application DB | 180 days |
| Auth replay nonce hash | C1 | Deterministic | Application DB | 10 minutes after signature expiry |
| Metrics/log metadata | C1 | Non-authoritative | Local telemetry/log sink | Backend policy; no content |
| Prompt/completion/tool body | C3 in default sample | Untrusted | Not enabled/persisted | None |
| Token/private key/password | C2 | Security material | Mounted file/process memory | Shortest operational lifetime; rotate/delete |
| Company/private data | C3 | Untrusted and unauthorized | Nowhere | Reject/stop demo/remove safely |

### Classification rules

- C0 is not trusted merely because it is public.
- A C2/C3 value cannot be downgraded by redaction after it has already entered
  a forbidden store; prevent ingestion first.
- IDs and hashes are C1 and may still be linkable; logs and errors remain
  bounded.
- Evidence summaries contain only validated public facts and source locators,
  not copied source files.
- Feedback and approval reasons reject secrets and are treated as untrusted text
  during display/export.
- Telemetry content capture remains disabled; enabling it requires a new
  classification, access, retention, and deletion decision.

## Assets and abuse impact

| Asset | Confidentiality | Integrity | Availability |
| --- | --- | --- | --- |
| Authentication keys/tokens | Critical | Critical | Medium |
| Authorization/policy configuration | Medium | Critical | High |
| Accepted event/run/job state | Low/medium | Critical | High |
| Checkpoints and approval state | Low/medium | Critical | High |
| Audit history | Medium | Critical | Medium |
| Public evidence provenance | Low | High | Medium |
| Side-effect identity/receipt | Medium | Critical | Medium |
| Release/dependency identity | Low | Critical | High |
| Local host/container boundary | High | Critical | High |

For this sample, the highest-impact outcomes are unauthorized state transition,
false evidence-backed claims, credential disclosure, arbitrary local process
execution, lost accepted runs, or a duplicate logical delivery.

## Threat register

Status values are `mitigated by design`, `verification required`, or
`prohibited`. Implementation tasks named in Controls must prove the design.

| ID | STRIDE / AI risk | Scenario and impact | Controls | Residual/status |
| --- | --- | --- | --- | --- |
| T01 | Spoofing | Attacker forges service/reviewer/operator identity | Asymmetric short-lived tokens, fixed issuer/audience/algorithm, typed principal mapping, loopback | Token theft remains during five-minute lifetime; B05 verification required |
| T02 | Spoofing/tampering | Forged webhook changes body/source/scope | RFC 9421 covered method/target/digest/key, configured source/scope, nonce claim | Signed profile test-only until B05 |
| T03 | Replay | Captured event, approval, or operator request repeats a mutation | Durable nonce plus business idempotency/fingerprint; approval version/hash; linked replay | Verification required B05/B07/B13 |
| T04 | Elevation | Caller supplies role, scope, source, workflow, tool, destination, or environment | Derive from trusted policy/registry; deny by default; object queries scoped | Verification required B05/B08 |
| T05 | Information disclosure | Out-of-scope object lookup reveals another resource | Query by scope+ID, return `404`, bounded errors | Verification required B05 |
| T06 | Tampering | Duplicate/racing worker commits stale result | Row locks, lease token fencing, optimistic version, one active attempt | Verification required B07/B10 |
| T07 | Repudiation | Actor denies approval/replay or audit history is altered | Same-transaction audit, stable actor/action hash/policy version; runtime cannot update/delete | DB admin remains trusted; B06/B13 |
| T08 | DoS | Oversized/recursive event exhausts parser/storage | Pre-parse byte limit, strict typed schema, bounded strings/items/depth, no run on reject | Verification required B01/B04 |
| T09 | DoS | Event flood fills durable queue/disk | Authenticated producer, rate/concurrency/backlog limits, bounded retention and alerts | Local single-host residual; B15/B16 |
| T10 | Prompt injection | Alert text says to ignore policy, reveal secrets, or call tools | Treat as data; fixed prompt boundary; deterministic route/policy/tool selection; structured output | Model disabled G2; adversarial C03 tests |
| T11 | Indirect prompt injection | Public graph/tool summary contains instructions | Validate schema; synthesize summaries from fields; do not copy `nextAction` as instruction; evidence-ID allow-list | C02/C03 verification |
| T12 | Sensitive disclosure | Secret/company data enters event, prompt, checkpoint, audit, log, or trace | C2/C3 prohibition, allow-listed models, content capture off, redaction, bounded state | Human paste/error residual; stop condition |
| T13 | Excessive agency | Model/tool output initiates mutation or external send | No general tool port; mutation ports unregistered; local receipt only; human-bound approval | Prohibited through G5 |
| T14 | Hallucination/insecure output | Model cites missing evidence or unsupported claim | Strict `AgentDecision`, evidence subset validation, provisional/review fallback, replay evaluation | Model disabled G2; C03/C06 |
| T15 | Tool poisoning | MCP changes catalog/description or returns malicious fields | Pin provider/lock; exact tool allow-list and response schema; ignore prose as control | C02 verification |
| T16 | Local code execution | Attacker changes MCP executable/args or compromised child reads host | Static argv, no shell, pinned checkout, minimal env, read-only FS, stdio, non-root, no secrets | Host maintainer trust remains; C02/B16 |
| T17 | Path traversal/exfiltration | MCP/event requests arbitrary project/path/index | Fixed `sock-shop` and service allow-list; reject absolute/parent paths; no arbitrary query/tool | C02 verification |
| T18 | Output/zip bomb | Dependency returns huge/deep response or stderr stream | Byte/item/depth/deadline bounds; kill child; `terminal_dependency` | C02 verification |
| T19 | Supply chain | Compromised image/package/toolkit/model changes behavior | Lockfiles/digests/release identity, minimal build inputs, scans/tests, capability preflight | Upstream compromise residual; B16/D05 |
| T20 | Unsafe deserialization | Crafted checkpoint executes code or loads unapproved type | Strict msgpack/minimal allow-list; no pickle; saver-owned schema | B11 verification |
| T21 | Cross-store inconsistency | Checkpoint advances but run/job summary does not | Stable thread/run IDs, at-least-once recovery, fenced state, reconciliation | Expected non-atomic gap; D04 |
| T22 | Duplicate side effect | Crash/replay sends same logical notification twice | Durable reserve/call/receipt protocol, stable key/hash, provider reconciliation | Local receipt only G2; B12/D04 |
| T23 | Ambiguous effect | Timeout occurs after provider may have accepted request | Persist `unknown`, reconcile before retry, disable provider lacking lookup/idempotency | External provider prohibited until C04 |
| T24 | Approval spoof/stale action | Approval applies to changed/expired interrupt or service identity approves | Human principal, exact hash/version/expiry, optimistic concurrency, one resume | B13 verification |
| T25 | Quarantine bypass | Normal operator replays malicious/poison event | Separate `quarantine:release` plus replay permission and audited reason | B05/B13 verification |
| T26 | Telemetry disclosure/tamper | Trace exports content/credentials or is treated as audit | Content off, redaction, sampling, optional backend, durable audit separate | B15 verification |
| T27 | Secret leakage | Secret appears in image/env dump/command/log/state | File mounts, minimum service access, ignored files, no command args, redaction tests | B03/B16 verification |
| T28 | Container escape/control | Runtime mounts Docker socket, runs privileged/root, or writes image FS | Non-root, read-only root, dropped capabilities, no-new-privileges, no socket | Container/kernel residual; B16 |
| T29 | SSRF/session theft | Future remote MCP fetches attacker URL or trusts session as identity | Remote MCP not enabled; new ADR requires fixed URL, TLS/auth/audience/session controls | Prohibited |
| T30 | Retention failure | Payload/checkpoint/audit survives policy or active state is deleted early | Authority-specific retention, supported saver delete, bounded jobs, audit/metrics | No backup guarantee; B06/D04 |
| T31 | Evidence poisoning | Public inventory edge is false/stale yet shown as runtime truth | Pin revision/hash, mark authored and `runtime_verified=false`, review fallback | Source-author correctness residual |
| T32 | UI/content injection | Reason/summary contains Markdown/HTML/script in future UI | Treat output as text, escape at renderer, never render raw provider HTML | UI outside repo; contract test before UI |
| T33 | Resource exhaustion | Retry storm or dependency outage amplifies work | One durable retry owner, full jitter/caps, no nested adapter retries, dead letter | B07/D04 |
| T34 | Destructive operator error | Teardown removes volumes or replay overwrites history | No automatic `down -v`, explicit destructive action, replay creates linked record | Local operator residual |

## Prompt-injection and model boundary

G2 uses no external model. When C03 adds an optional model, the system prompt
and code—not alert/evidence content—define the task. Inputs are separated into:

- trusted policy: fixed instruction/version and allowed output schema;
- untrusted alert data: bounded typed fields;
- untrusted evidence data: bounded refs and summaries with source IDs.

The model receives no credential, tool client, database handle, raw source
corpus, arbitrary URL fetcher, notification destination, or permission grant.
Its output is a proposal. Deterministic code rejects unknown evidence IDs,
unknown fields, invalid enums, excessive text, and disallowed outcomes.

Prompt-injection detection is defense in depth, not the primary boundary.
Security does not depend on perfectly recognizing malicious natural language.

## MCP subprocess boundary

The stdio server is executable code with the worker's OS privileges, not merely
data. Before C02 enables it:

1. exact executable, argv, working directory, toolkit revision, and lock digest
   are deployment configuration;
2. `shell=false` and a minimal environment are mandatory;
3. checkout and source metadata are read-only;
4. no private home, SSH, cloud, Docker, database, or model credential is
   mounted/passed;
5. only `list_tools`/`validate_project` at startup and
   `get_service_details` at runtime are accepted;
6. stdout is protocol-only; stderr and responses are bounded;
7. unexpected tool catalog/version/output/exit makes the adapter unready;
8. the worker owns cancellation and child termination.

An HTTP wrapper is not equivalent and remains prohibited without a new review.

## Side-effect and approval boundary

The sample's “notification” produces only a durable local receipt. Even so, the
full reserve/call/outcome protocol is required so later adapters cannot bypass
it.

No LLM can approve its own recommendation. Approval URLs/tokens are not bearer
capabilities. The API re-loads authoritative run state and binds a human
decision to the current action hash, version, scope, actor, policy, and expiry.

Auto-send remains disabled. E08 may implement only a disabled, allow-listed
policy mechanism; enabling a user-visible effect requires a separate post-G5
decision.

## Safe failure matrix

| Failure | Safe outcome |
| --- | --- |
| Invalid/missing identity or policy | Reject; no durable business mutation |
| Unknown event/version/workflow | Reject before run/job |
| Database admission failure | No accepted response; retry same idempotency key |
| Worker death | Lease expires; same job/thread resumes |
| Checkpoint unavailable | No successful run transition; retry/dead-letter |
| Evidence absent/stale/truncated | Provisional/review; no suppression/delivery |
| Model absent/invalid/timeout | Deterministic fallback/review |
| MCP child mismatch/crash | Adapter unready; bounded retry/review |
| Approval stale/expired/changed | Conflict; no resume job |
| Side-effect outcome unknown | Persist unknown; reconcile; no blind retry |
| Telemetry unavailable | Workflow behavior unchanged |
| Retention job failure | Preserve data, alert from durable state; never guess deletion |
| C2/C3 data discovered | Stop demo, prevent further processing, remove access, follow repository security process |

## Accepted residual risks for the sample

| Residual risk | Why accepted | Company reuse requirement |
| --- | --- | --- |
| Bearer token replay for up to five minutes | Loopback-only fixture with synthetic data | Sender constraint/revocation and real IdP |
| Trusted local host administrator | Single-user hackathon workstation | Hardened runtime/host and operational ownership |
| Single PostgreSQL/volume failure domain | Demonstrates semantics, not HA | Backup, restore, encryption, HA/DR |
| No application-level checkpoint encryption | Only bounded public/sample data allowed | Classification and key-management decision |
| Public authored graph may be stale/wrong | Marked as authored, not runtime truth | Source governance/freshness SLO |
| No automated backup | Disposable local demo | Approved PITR and deletion alignment |
| Optional dependency supply-chain compromise | Pins/tests reduce but cannot eliminate | Registry/provenance/signing/vulnerability process |

None of these accept company data, external delivery, public exposure, or
mutation.

## Security verification and traceability

| Control area | Required evidence |
| --- | --- |
| Input/classification | B01/B02 schema, size, serialization, forbidden-field tests |
| Identity/scope/replay | B05 positive/negative authorization and nonce/idempotency tests |
| Durable integrity | B06-B13 migration, lease, checkpoint, side-effect, approval tests |
| Secret/runtime boundary | B03/B16 startup, permissions, image, network, signal tests |
| Logging/telemetry | B15 redaction, content-off, cardinality, dependency-state tests |
| External evidence | C02 path/tool/version/output/injection/timeout tests |
| Model output | C03 evidence-ID, injection, schema, timeout/budget tests |
| External effect | C04 remains disabled until approved contract/reconciliation tests |
| Safe workflow fallback | C06 missing/stale/invalid/low-confidence tests |
| Adversarial evaluation | D01-D04 poison/replay/failure fixtures and resilience report |
| Release identity | D05 immutable code/contract/policy/tool/dataset versions |

Gate G2 cannot pass until its applicable `verification required` threats have
tests. Gate G3 cannot pass until the C/D controls do.

## Security operations

Stop the demo immediately on:

- any C2/C3 value in Git, business state, checkpoint, audit, or telemetry;
- unauthorized or cross-scope access;
- accepted-run loss or audit mutation;
- duplicate logical receipt or external delivery;
- arbitrary command/tool execution;
- unsupported claim presented without its evidence limitation.

Preserve bounded IDs, hashes, timestamps, and safe logs needed for diagnosis.
Do not copy tokens, raw payloads, or secret tool output into an issue. Rotate
affected fixture/database secrets, disable the relevant adapter/profile, and
re-run the negative/resilience tests before continuing.

## Review triggers

Repeat this threat model before:

- binding beyond loopback or adding a reverse proxy;
- using company/private/PII data;
- enabling a real identity provider, model, remote MCP, telemetry content, or
  notification provider;
- changing the allowed MCP tools or making the toolkit checkout writable;
- adding another resource scope/team/tenant;
- enabling publication, action, auto-send, or any mutation;
- changing retention, backup, encryption, approval, or audit policy;
- accepting a breaking external contract or major dependency/runtime change;
- moving from Compose to a shared host, cluster, or cloud.

## References

- [OWASP threat-modelling guidance](https://owasp.org/www-project-security-culture/stable/6-Threat_Modelling/)
- [OWASP Top 10 for LLM and generative-AI applications](https://genai.owasp.org/llm-top-10/)
- [OWASP excessive-agency risk](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)
- [NIST AI 600-1 Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)
- [MCP security best practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
- [ADR-0003: Persistence and retention](../adr/0003-persistence-checkpoints-and-retention.md)
- [ADR-0004: Authentication and authorization](../adr/0004-authentication-authorization-and-replay.md)
- [ADR-0005: Local Compose deployment](../adr/0005-local-compose-deployment.md)
- [ADR-0006: External adapter contracts](../adr/0006-external-adapter-contracts.md)
