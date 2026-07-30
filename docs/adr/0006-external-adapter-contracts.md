# ADR-0006: External Adapter Contracts and Sample Integrations

- Status: accepted for the public hackathon sample
- Date: 2026-07-30
- Decision owners: Repository Owner and Platform/Safety Reviewer (sample roles)
- Scope: adapter lifecycle, error semantics, evidence boundaries, current
  service-graph integration, local reasoning/notification, and future external
  contract approval
- Depends on: ADR-0001 through ADR-0005

## Context

This repository owns orchestration and shared contracts. It must not absorb
source indexing from `service-graph-toolkit`, alert collection/policy/delivery
from `sre-alert-agent`, playbooks from `sre-skills`, or the user-facing wiki
from `code-atlas-workbench`.

The current Python ports are synchronous and broad. Demo implementations return
in-memory results. They are useful reference code but do not yet define async
lifecycle, timeouts, response bounds, version compatibility, error categories,
or durable side-effect behavior.

The public sample has one available external evidence source: the neighboring
public `service-graph-toolkit` checkout and its Sock Shop project. On
2026-07-30, its revision
`f5b59398c9cdbca04d2e2cc07d33b26ae4323b69` validated seven services and
exposed a local stdio MCP server. This is evidence of the current development
contract, not a forever-compatible version or a company service approval.

No company alert ingress, model gateway, Teams/Jira delivery endpoint, remote
MCP service, wiki publisher, or action service is approved for this sample.

## Decision summary

Keep adapters behind typed async ports. Deterministic application code selects
the port, operation, scope, project, service, deadline, and limits. An LLM may
perform semantic judgment through a reasoning port but never selects arbitrary
tools, executables, destinations, credentials, or authorization context.

Gate G2 uses only:

- synthetic typed events submitted through the authenticated API;
- deterministic local evidence fixtures;
- deterministic local alert reasoning;
- a receipt-only notification adapter behind durable side-effect handling.

The current `DemoKnowledge` implementation is reference code, not the approved
Gate G2 fixture: it includes illustrative non-Sock-Shop locators. B10/C02 must
replace it with evidence containing only validated public Sock Shop metadata.

Gate G3 may replace the evidence fixture with a read-only Sock Shop adapter
using the existing `service-graph-toolkit` stdio MCP server. It does not enable
external notification or mutation.

Every live external adapter requires a pinned contract/release identity,
consumer-driven contract tests, an A08 threat-model update, explicit egress and
credential configuration, and approval from the owning repository/system.
Unknown or unapproved adapters fail startup.

## Ownership and approval matrix

| Capability | Owning boundary | Public sample status | Cross-repository change |
| --- | --- | --- | --- |
| Synthetic alert fixture | This repository | Enabled for G2 | None |
| Deterministic evidence fixture | This repository | Enabled for G2 | None |
| Sock Shop graph evidence | `service-graph-toolkit` | Consumer contract accepted for C02; live packaging pending | None requested; current stdio interface consumed as-is |
| Deterministic alert reasoning | This repository | Enabled for G2 | None |
| Model reasoning gateway | Future provider/platform owner | Disabled | Contract and owner approval required for C03 |
| Local receipt-only notification | This repository | Enabled for G2 | None |
| Alert/Teams delivery | `sre-alert-agent` | Disabled | Producer and delivery contracts require owner approval for C01/C04 |
| SRE knowledge/actions | `sre-skills` | Disabled | Separate post-pilot contract and security gate |
| Wiki/publication | `code-atlas-workbench` | Disabled | Deferred; owner contract required |

A07 is accepted for the public sample because its enabled dependencies are
locally owned and the toolkit is consumed through an already present public,
read-only interface without an upstream modification. This does not record
approval for a future company API or for changes in another repository.

## Common adapter contract

### Async lifecycle

I/O-bearing ports use async methods and an explicit lifecycle:

```text
configure immutable settings
    -> start / verify capabilities
    -> ready
    -> bounded concurrent calls
    -> stop accepting calls
    -> cancel/drain
    -> close
```

One adapter instance is owned by one process lifecycle. It may own a connection
pool or supervised child process; it is never serialized into graph state.
Startup verifies required capabilities and configured contract versions without
performing a business mutation.

Each call receives a bounded immutable context containing:

- run/correlation ID;
- resource scope and authorized operation;
- absolute monotonic deadline or remaining timeout;
- adapter contract/release version;
- operation-specific idempotency key only when the port can cause an effect.

It never receives bearer tokens, webhook signatures, database sessions, raw
authorization claims, or a general-purpose tool registry.

### Typed requests and results

Port requests and results are strict versioned models with unknown fields
rejected at external boundaries. They contain identifiers, bounded summaries,
and evidence references rather than arbitrary nested provider payloads.

The adapter:

- validates and canonicalizes before use;
- enforces configured input/output byte, item, and concurrency limits;
- returns a typed result or typed `AdapterError`;
- never returns a live client, exception object, credential, or unbounded body;
- records provider/tool version and latency as bounded metadata;
- does not write workflow state, audit rows, or side-effect records directly.

The worker/application service owns durable state and audit transactions.
Telemetry observes the call but is not its authority.

### Error taxonomy

Adapters do not hide retries. They classify an outcome; ADR-0002 worker policy
owns persisted retry timing and attempt budgets.

| Adapter outcome | ADR-0002 category | Required behavior |
| --- | --- | --- |
| Timeout, connection loss before a read, temporary unavailable, rate limit | `retryable_transient` | No result; worker may retry from persisted policy |
| Unsupported request or impossible validated input | `terminal_input` | Fail the operation without automatic retry |
| Missing capability, unsupported contract, malformed/oversized response | `terminal_dependency` | Fail closed; readiness false until compatible |
| Credential/authentication/authorization failure | `terminal_policy` | Fail closed; no credential in error; operator/config review |
| External effect may have occurred but no receipt is known | `ambiguous_side_effect` | Persist `unknown` and reconcile; never blind-retry |
| Injection, forbidden content/type, path escape, or protocol corruption | `poison_or_security` | Quarantine according to policy |
| Local cancellation or lost lease | `worker_lost` | Stop adapter work; do not commit a result |

Adapters may perform protocol-required reconnection, but they do not implement
an independent exponential retry loop. Error messages are bounded and reduced
to category, stable fingerprint, safe reason code, and dependency identity.

### Security and observability

- Credentials enter only the adapter that needs them through process secret
  configuration.
- Tool/provider output is untrusted data and never interpreted as instructions.
- Adapter selection and tool names are server configuration, never event/model
  content.
- Logs/traces contain dependency, operation, duration, outcome, and safe IDs,
  never request/response bodies by default.
- Trace content remains disabled unless an allow-listed redactor and review
  explicitly enable bounded fields.
- Read adapters cannot invoke mutation tools through the same client.
- Side-effect adapters receive a stable application idempotency key.

## Service graph knowledge contract

### Current provider evidence

The current public toolkit contract was inspected and validated locally:

- project `sock-shop` validates with seven services;
- the authored checkout path includes
  `front-end -> orders -> payment` and
  `front-end -> orders -> shipping`;
- the MCP server uses local stdio transport;
- responses use the bounded envelope
  `summary`, `data`, `sources`, `truncated`, and optional `nextAction`;
- `get_service_details(project="sock-shop", service="orders")` returns
  incoming/outgoing authored edges sourced from
  `projects/sock-shop/inventory.yaml`.

The provider owns inventory validation, indexing, generated artifacts, and MCP
tool behavior. This repository owns only request selection, response validation,
conversion into `EvidenceRef`, and orchestration fallback.

### Consumer request

The broad current `KnowledgePort.search(query: str)` is migrated in C02 to an
async structured request:

```text
EvidenceQuery v1
  scope_id = "sock-shop-sample"
  project_id = "sock-shop"
  service_ids = server-selected allow-listed services
  purpose = "alert-impact"
  max_results <= 8
  deadline
```

The workflow/event registry maps validated event subjects to services.
Free-form event text or model output cannot choose a project, service, MCP tool,
filesystem path, repository index, or result limit.

For the first live adapter, the only runtime business tool is
`get_service_details`. `validate_project` and `list_tools` are startup/preflight
operations. Indexed code search, symbol context, impact, generated context, and
service-map tools remain disabled until their source snapshot, output bounds,
and packaging are separately tested.

### Stdio process boundary

The current toolkit has no approved network transport. The local C02 adapter:

- launches one long-lived MCP child per worker through the SDK stdio transport;
- uses a static executable and argument vector with `shell=false`;
- pins the toolkit Git revision and `mcp-server/package-lock.json` digest in
  release metadata;
- sets `SERVICE_GRAPH_ALLOWED_PROJECTS=sock-shop`;
- passes a minimal allow-listed environment and no company credential;
- mounts/uses the entire toolkit checkout read-only; the initially allowed
  tools require no generated/index writes;
- bounds startup, call, stderr, message, and shutdown sizes/times;
- treats unexpected stdout, tool catalog, protocol version, exit, or response
  shape as a dependency contract failure;
- closes the child on worker shutdown and restarts it only under a bounded
  lifecycle policy.

This matches MCP's local stdio model where the client owns the child process.
An event, model, prompt, or MCP response can never alter the command or
environment.

The Gate G2 Compose image does not include Node or the sibling repository.
Live host-mode C02 may use an operator-supplied pinned checkout. Adding the
adapter to Compose requires `service-graph-toolkit` to publish an approved
versioned artifact/image or approve a reproducible additional build context.
Until then, the Compose live-knowledge profile remains undefined and cannot
silently bind-mount an arbitrary neighboring directory.

A future Streamable HTTP provider is a new deployment/security decision with
TLS, authentication, authorization, protocol-version, session, timeout, and
SSRF controls. This ADR does not expose the local stdio server over HTTP.

### Response validation and evidence mapping

The adapter accepts at most:

- 128 KiB encoded response;
- 8 evidence results;
- 16 source locators;
- configured string/collection depths and lengths;
- only the expected envelope and per-tool schema.

It rejects absolute paths, parent traversal, unknown project/service IDs,
unknown source kinds, non-finite numbers, duplicate conflicting records, and
unrequested tool content. `truncated=true` is a valid incomplete result, never
evidence of absence.

An accepted authored edge becomes a bounded `EvidenceRef` with:

- source `service-graph-toolkit`;
- kind `graph`;
- locator under `projects/sock-shop/inventory.yaml`;
- revision composed from the pinned toolkit commit and validated inventory
  SHA-256;
- deterministic summary built from validated edge fields;
- observed time from the orchestrator clock;
- metadata marking `authored-declaration` and `runtime_verified=false`.

Tool prose and `nextAction` are not copied into prompts as instructions. A
numeric confidence of `1.0` means exact schema extraction fidelity only; the
metadata still says `runtime_verified=false`. It is not proof of runtime
behavior, and decisions must preserve that limitation.

Unavailable, stale, truncated, or malformed evidence cannot support suppression
or delivery. The workflow records a safe category and moves to review/fallback
according to C06.

## Reasoning contract

Gate G2 uses a deterministic local alert reasoner. It consumes only a validated
alert model and bounded evidence references and returns a strict
`AgentDecision`. It performs no network call and makes no claim of model
quality.

C03 may add a model-backed adapter only for semantic impact/recommendation. Its
contract must:

- produce the same strict decision model;
- cite only evidence IDs supplied in the request;
- reject unknown/missing citations and unsupported claims;
- set model/provider/prompt contract versions in release metadata;
- enforce context, output, timeout, token, and cost budgets;
- treat retrieved and alert text as data, not system instructions;
- return deterministic fallback/review on unavailable or invalid output;
- keep normalization, routing, policy, authorization, evidence validation,
  thresholds, and delivery decisions outside the model.

No model provider is selected or approved by this ADR. Model credentials and
raw traffic never enter graph state or audit.

## Notification and side-effect contract

Gate G2 uses a receipt-only local adapter. It renders the bounded sample message
and returns a deterministic receipt derived from effect kind, destination,
idempotency key, and canonical request hash. It does not send a network request
or create a user-visible notification.

All notification calls go through ADR-0003 durable `side_effects`:

```text
reserve stable effect -> commit
    -> call adapter outside transaction
    -> persist receipt/outcome -> commit
```

The adapter request contains:

- contract version, run ID, effect kind, fixed destination;
- bounded rendered message and content hash;
- stable idempotency key;
- deadline.

The result is one of `succeeded` with a bounded receipt,
`retryable_failure`, `terminal_failure`, or `unknown`. Only a durable
`succeeded` record counts as delivered. The adapter cannot invent a new
destination, bypass approval/policy, or mark the database itself.

A future `sre-alert-agent` adapter must preserve this contract and add
provider-side idempotency or lookup/reconciliation. Its accepted receipt,
retryable/terminal errors, ambiguous timeout behavior, authentication, message
schema, and ownership require a C04 contract approved in that repository.
Teams delivery is not enabled by this ADR.

## Event producer contract

The sample producer is `demo-event` from ADR-0005. It sends only sanitized,
versioned Sock Shop fixtures to `POST /v1/events` using an ADR-0004 fixture
identity and stable idempotency key.

This repository does not collect Sentry events. C01 will define a
consumer-driven alert envelope and authentication fixture for
`sre-alert-agent`. Until its owner approves that version/signature/retry
contract, no real alert producer is configured.

## Disabled ports and workflows

The deployed API registry exposes only alert review. Other existing reference
graphs remain library/demo code and are not remotely invocable.

| Port/capability | Gate G2 behavior |
| --- | --- |
| Knowledge | Deterministic local fixture |
| Reasoning | Deterministic local alert reasoner |
| Notification | Durable local receipt only |
| Extraction | Not registered |
| Publication | Not registered |
| Action execution | Not registered; any request fails terminal policy |
| Arbitrary MCP/tool execution | No port exists |

An unavailable port fails startup if an enabled workflow requires it. It never
falls back to a broader or mutating implementation.

## Versioning and compatibility

Every adapter declares:

- adapter name and contract version;
- provider/tool release identity;
- supported request/result schema versions;
- enabled operation/capability set;
- safe configured limits.

These values become part of D05 release metadata and bounded run metadata.
Startup rejects missing required capabilities or incompatible major versions.
Additive provider fields are ignored only when the explicitly versioned
boundary permits them; external response models otherwise reject unknown
fields.

Breaking contract changes require:

1. a new contract version;
2. updated sanitized fixture/fake server;
3. consumer-driven contract tests;
4. migration/rollback behavior;
5. approval from both owning boundaries before enablement.

## Contract tests

Each adapter implementation must pass against a fake/sandbox without real
credentials:

- success at exact input/output limits;
- timeout, cancellation, process/connection loss, and graceful close;
- malformed, oversized, truncated, unknown-version, and forbidden content;
- authorization/scope/tool allow-list violations;
- deterministic error-category mapping without raw provider data;
- redacted logs/traces;
- concurrency and lifecycle ownership;
- compatibility with pinned provider fixture/tool catalog.

Knowledge tests also cover stale revision, path traversal, missing source,
untrusted prose, and evidence result limits. Reasoning tests cover injection
content and unknown citations. Notification tests cover duplicate key,
retryable/terminal failure, crash after effect, ambiguous timeout, and
reconciliation.

Live smoke tests are explicit, opt-in, and never part of credential-free unit
tests. The toolkit smoke may use only public Sock Shop metadata.

## Alternatives considered

### Copy Sock Shop graph data or indexing logic into this repository

Rejected. It would violate repository ownership and create a stale second
implementation. The local fixture may model the contract, but the provider
owns live inventory and indexing.

### Let the LLM choose MCP tools and arguments

Rejected. Routing, project/service scope, tool allow-list, limits, and evidence
validation are deterministic application policy.

### Expose the current stdio server as an unauthenticated HTTP sidecar

Rejected. The provider explicitly documents a local stdio server. Remote
transport needs its own authenticated deployment contract.

### Bind-mount `../service-graph-toolkit` into the default Compose worker

Rejected. It makes the build depend on an arbitrary mutable sibling path and
mixes unpinned Node/source dependencies into Gate G2.

### Enable a real model and Teams notification for hackathon impact

Rejected as a default. Optional external calls would add credentials, cost,
privacy, delivery, and ownership risks before contract and threat review.

### Retry inside every adapter

Rejected. Nested retry loops violate the durable worker attempt budget and make
shutdown/latency behavior unpredictable.

## Consequences

### Benefits

- Repository ownership remains explicit.
- Gate G2 is deterministic, credential-free, and side-effect local.
- The real public Sock Shop graph can be integrated without copying its logic.
- Tool and model output remain untrusted evidence, not control input.
- Adapter failure behavior maps to durable workflow policy.
- Cross-repository enablement has a visible approval gate.

### Costs and limits

- Existing synchronous ports need migration in B10/C02.
- Live service-graph use initially runs only in pinned host mode.
- Compose packaging waits for a provider artifact/build agreement.
- The local reasoner and receipt adapter do not demonstrate a real model or
  notification provider.
- Contract fixtures and compatibility tests add maintenance.

## Verification required by later tasks

- B10 migrates I/O ports to async lifecycle without wrappers that block the
  event loop.
- B12 routes the local receipt adapter through durable side-effect state.
- C02 validates the pinned toolkit tool catalog, Sock Shop project, bounds,
  lifecycle, evidence mapping, and all failure cases.
- C03 proves model output cannot select tools/policy or cite unknown evidence.
- C04 remains disabled until the external delivery owner approves its contract.
- C05 can switch adapters only through validated startup configuration.
- A08 threat-models stdio child execution, untrusted evidence, model input,
  side-effect ambiguity, egress, and cross-repository supply chain.

## References

- [Model Context Protocol architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [Model Context Protocol transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- `service-graph-toolkit/shared/mcp/tool-contracts.md` at the validated sibling revision
- `service-graph-toolkit/docs/MCP-DEMO.md` at the validated sibling revision
- `service-graph-toolkit/projects/sock-shop/README.md` at the validated sibling revision
- [ADR-0001: Async runtime and lifecycle](0001-async-runtime-and-lifecycle.md)
- [ADR-0002: PostgreSQL durable delivery](0002-postgres-durable-delivery.md)
- [ADR-0003: Persistence, checkpoints, and retention](0003-persistence-checkpoints-and-retention.md)
- [ADR-0004: Authentication, authorization, and replay](0004-authentication-authorization-and-replay.md)
- [ADR-0005: Local Compose deployment](0005-local-compose-deployment.md)
