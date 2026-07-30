# ADR-0004: Authentication, Authorization, Approval Identity, and Replay Protection

- Status: accepted for the public hackathon sample
- Date: 2026-07-30
- Decision owners: Repository Owner and Platform/Safety Reviewer (sample roles)
- Scope: API caller identity, webhook authentication, authorization policy,
  approval identity, launch scope, and request replay protection
- Depends on: ADR-0002 and ADR-0003

## Context

The control plane will admit events, expose run status, accept feedback, record
human approval decisions, and allow bounded operator replay. These operations
must not trust caller-supplied source, workflow, scope, role, or actor fields.
Authentication and authorization must complete before a durable run, job,
approval, feedback record, or operator action is created.

The first implementation is a public, local hackathon sample using synthetic
Sock Shop alerts. It has no company identity provider, launch team, tenant
directory, or production webhook secret. The sample still needs a secure
contract that does not normalize an unauthenticated demo mode or imply that a
local identity fixture is suitable for company deployment.

Authentication proves a caller identity. Authorization deterministically
decides whether that identity may perform one action on one scoped resource.
Idempotency and replay protection are separate controls: a valid caller can
retry safely, while a captured or altered request must not create another
mutation.

## Decision summary

The API is an OAuth resource server, not an identity provider. It accepts
short-lived, asymmetrically signed JWT access tokens following the RFC 9068
profile. It never accepts an OpenID Connect ID token as an API access token.

A configured webhook producer that cannot obtain an access token may instead
use RFC 9421 HTTP Message Signatures with RFC 9530 content digests. Each route
and producer has exactly one configured authentication profile; the server does
not fall back from a failed profile to another one.

Authorization is deterministic, deny-by-default policy over:

- authenticated principal type and stable issuer/subject identity;
- route action;
- OAuth permission scopes;
- the fixed sample resource scope;
- configured event source and server-selected workflow;
- resource state and, for approvals, the bound action/version/expiry.

The public sample has one resource scope, `sock-shop-sample`, and one
environment, `demo`. This is launch-group isolation, not a claim of
multi-tenant security. Company reuse requires a new identity, scope, policy,
deployment, and threat-model decision.

## Trust boundaries and principal types

| Principal type | Example | Permitted purpose |
| --- | --- | --- |
| `service` | Synthetic alert producer | Admit allow-listed event sources; read its accepted run |
| `reviewer` | Local human demo reviewer | Read runs/approvals, decide a bound approval, submit feedback |
| `operator` | Local demo operator | Read runs, manually replay eligible failures with a reason |
| `safety_reviewer` | Sample safety role | Release quarantine only when separately permitted |
| `observer` | Metrics/demo observer | Read explicitly exposed health or metrics only |

Principal type is derived from trusted issuer/client policy. A token cannot
promote itself by supplying a role, email address, group name, or display name.
A principal has a stable actor identity formed from the validated `iss` and
`sub` pair. Audit records use a bounded opaque representation of that pair
and never use an email address as identity.

Service and human identities are distinct. A service token cannot decide a
human approval. A human token cannot claim an event producer source merely by
possessing `events:write`.

## JWT access-token profile

Protected API routes accept `Authorization: Bearer <access-token>` only over
TLS, except on an explicitly loopback-bound local sample listener. Query-string
tokens, cookies, API keys, ID tokens, and unsigned tokens are rejected.

### Required validation

Validation is performed by deterministic code before request-body semantic
processing:

1. bound the encoded token and JOSE header size;
2. use the unverified `iss` only as an exact lookup key in a static trusted
   issuer allow-list; never fetch an unvalidated `iss`, `jku`, `x5u`, or
   other token-provided URL;
3. resolve `kid` only in that issuer's pinned or discovered JWKS;
4. require `typ` to be `at+jwt` or `application/at+jwt`;
5. require an allow-listed asymmetric algorithm and verify the signature;
6. require exact trusted `iss` and configured API `aud`;
7. validate `exp`, `nbf` when present, and a reasonable `iat`;
8. require non-empty bounded `sub`, `client_id`, and `jti`;
9. reject a token whose issued lifetime exceeds five minutes in the sample;
10. allow at most 30 seconds of configured clock skew;
11. normalize permission scopes and resource scopes from the trusted issuer
    contract, rejecting malformed, duplicate, or excessive claims;
12. derive the principal type and policy inputs from configured issuer/client
    mappings.

The accepted algorithm set is deployment configuration and never comes from
the token. `none` and symmetric JWT algorithms are not allowed. Keys are
bound to one issuer, use, and algorithm. JWKS retrieval uses only a trusted
HTTPS location, has bounded time/size, caches known keys for rotation, and
fails closed when an unknown key cannot be refreshed.

The API never performs authorization from an unverified claim. It never logs,
traces, checkpoints, audits, or persists the bearer token or JOSE material.

### Local sample issuer

The repository may provide a development token command in B03. It must:

- bind the API to loopback unless the operator supplies an external security
  configuration;
- generate an ephemeral asymmetric key outside Git with restrictive file
  permissions;
- issue five-minute sample tokens for fixed fixture principals and
  `sock-shop-sample` only;
- print tokens only when explicitly requested and never log them from the API;
- publish only the ephemeral public verification key to the API;
- invalidate outstanding sample tokens when the local key is replaced.

There is no `AUTH_DISABLED` mode, committed private key, shared default token,
password database, login form, or production identity-provider implementation.

Bearer tokens are replayable while valid. Short lifetime, audience restriction,
TLS, and idempotent mutations bound the local sample risk. Before company use,
the deployment owner must decide revocation and sender-constrained access
tokens such as mTLS or DPoP; this ADR does not claim that bearer tokens alone
prevent theft and replay.

## Signed webhook profile

RFC 9421 HTTP Message Signatures are an alternative authentication profile only
for event producers explicitly configured for `POST /v1/events`. This profile
does not accept a simultaneous bearer token, and other mutation routes do not
accept webhook signatures.

The producer key ID, asymmetric verification key, algorithm, source, permitted
event types, and resource scope are configured together. Runtime algorithm or
key-location signaling from the request cannot override them.

The signature must cover:

- `@method`, `@authority`, and `@target-uri`;
- `content-type` and `content-digest`;
- `idempotency-key`;
- the signature parameters `created`, `expires`, `nonce`, `keyid`, and
  the application tag `platform-agent-event-v1`.

The API:

1. rejects a request before JSON parsing if a required component is absent;
2. verifies a SHA-256 `Content-Digest` against the exact received content
   bytes;
3. verifies the message signature with the configured producer key;
4. requires `created` no more than five minutes in the past or 30 seconds in
   the future;
5. requires `expires` after `created` and no later than five minutes after
   it, and rejects an expired signature;
6. requires at least 128 bits of unpredictable nonce value;
7. derives source and scope from producer configuration, not the body;
8. reserves the nonce in durable `auth_replay_claims` in the same application
   transaction as event admission.

The canonical external URL must be provided by trusted proxy configuration.
Untrusted forwarded host or protocol fields never influence signature
verification.

A repeated `(authenticator_id, nonce)` is rejected and creates no second
mutation. If a producer needs to retry after an unknown response, it signs a
new request with a fresh nonce and the same `Idempotency-Key`. ADR-0003 then
returns the original run for the same canonical fingerprint or rejects changed
content. Thus signature replay is rejected without sacrificing safe business
retry.

The nonce claim rolls back if admission rolls back. Expired claims are retained
for ten minutes beyond signature expiry, then deleted in bounded batches.
Invalid signatures and unauthorized requests do not reserve nonces or create
runs.

## Resource scope and launch group

The public sample defines:

| Dimension | Allowed value | Source of authority |
| --- | --- | --- |
| Resource scope | `sock-shop-sample` | Trusted token claim plus policy, or configured webhook producer |
| Environment | `demo` | Server deployment configuration |
| Event source | `synthetic-sock-shop` | Client/producer policy |
| Workflow | Alert-review workflow only | Server event-type registry |
| Evidence | Public Sock Shop/sample references | Validated event and retrieval policy |
| Side effect | Local deterministic notifier | Adapter configuration |

The request body does not select `scope_id`, environment, arbitrary workflow,
adapter, model, prompt, or tool. The API supplies trusted scope context to every
application query and mutation. Object lookup uses both `scope_id` and object
ID; a caller outside the object scope receives a not-found response rather than
proof that the object exists.

Policy configuration is versioned, code-reviewed, loaded at startup, and
immutable for the process lifetime. The sample has no runtime role editor,
group synchronization, delegated administration, wildcard scope, or
cross-scope query.

## Permission model

OAuth permission scopes name API actions; resource scope identifies which
sample resources those actions may affect. Both must match.

| Route/action | Principal | Required permission | Additional policy |
| --- | --- | --- | --- |
| `POST /v1/events` | `service` | `events:write` | Configured source/event type; JWT or signed-webhook profile |
| `GET /v1/runs/{run_id}` | Service or human | `runs:read` | Same resource scope |
| `GET /v1/approvals` | Human | `approvals:read` | Same scope; bounded filters |
| `POST /v1/runs/{run_id}/resume` | `reviewer` | `approvals:decide` | Current bound approval only |
| `POST /v1/runs/{run_id}/feedback` | `reviewer` | `feedback:write` | Visible run in same scope |
| Manual replay | `operator` | `runs:replay` | Eligible terminal state, reason, idempotency key |
| Quarantine release | `safety_reviewer` | `quarantine:release` and `runs:replay` | Explicit security review |
| `GET /health/live` | None | None | Reveals process liveness only |
| `GET /health/ready` | Platform identity | `health:read` | Internal listener or ingress policy |
| `GET /metrics` | `observer` | `metrics:read` | Internal listener or ingress policy |

Possessing a permission is necessary but not sufficient. The deterministic
policy also checks principal type, resource scope, source/workflow allow-list,
environment, object state, and operation-specific constraints. There is no
administrator wildcard permission in the sample.

Authentication and authorization stay outside graph nodes. The graph receives
a bounded immutable authorization context containing actor ID/type, resource
scope, policy version, and approved operation—not a token or mutable claims
dictionary. Graph or LLM output can never grant a permission.

## Approval identity and binding

An approval is a human decision on one exact durable interrupt, not a bearer
link or generic permission to resume a run.

The request includes:

- run ID and positive approval version;
- decision `approved` or `rejected`;
- the exact action/interrupt hash presented for review;
- a bounded reason;
- an `Idempotency-Key`.

In one transaction, the API:

1. authenticates a `reviewer` and checks `approvals:decide`;
2. loads the run by caller scope and ID;
3. requires `waiting_approval`, an unexpired interrupt, the current approval
   version, and an exact action hash;
4. binds the stored decision to actor ID/type, policy version, decision, reason,
   action hash, and database decision time;
5. records the idempotency result and audit event;
6. for approval, creates exactly one resume job and moves the run to `queued`;
7. for rejection, moves the run to `rejected` without a resume job.

Repeated requests with the same key and fingerprint return the prior bounded
result. Changed content, a stale version/hash, an expired interrupt, an
unauthorized actor, or a second decision creates no resume job.

The sample's separation of duties is between a service event producer and a
human reviewer. It does not claim a production two-person rule. Company reuse
must decide requester/approver separation, privileged-access management,
break-glass behavior, and reauthorization requirements.

## Operator replay and quarantine

Automatic replay is forbidden by ADR-0002. Manual replay additionally requires:

- a human `operator` with `runs:replay`;
- same-scope object access;
- an eligible terminal or closed dead-letter state;
- a bounded reason and `Idempotency-Key`;
- a new linked job or run that preserves the original history;
- an audit record with policy version and actor identity.

Quarantine release also requires a `safety_reviewer` with
`quarantine:release`. A normal operator cannot release quarantine. Bulk replay
and mutation of original attempt history remain out of scope.

## Error and disclosure behavior

| Condition | Response class | Durable mutation |
| --- | --- | --- |
| Missing, malformed, expired, or invalid authentication | `401` | None |
| Valid identity lacks permission or configured source | `403` | None |
| Object absent or outside caller resource scope | `404` | None |
| Replayed webhook nonce, stale approval, or idempotency conflict | `409` | No business mutation |
| Authenticated malformed input | `400` or `422` | None |
| Payload exceeds pre-parse bound | `413` | None |

Responses and logs are bounded and do not disclose token contents, key
material, other scopes, policy internals, or whether an out-of-scope object
exists. Rate limiting and denial-of-service controls are deployment concerns in
A07, but authentication parsing and key refresh are bounded here.

## Audit and observability

Every accepted mutation records:

- actor ID/type and authentication profile;
- resource scope and policy version;
- action, outcome, reason code, and request/correlation ID;
- affected bounded resource identifiers;
- approval/action hash or request fingerprint where applicable.

Authorization denials produce bounded security telemetry and sampled logs.
High-risk valid-but-denied operator actions may create a bounded audit event,
but an unauthenticated request cannot force unbounded durable audit growth.

Tokens, signatures, cookies, authorization headers, private keys, JWKS bodies,
emails, full group lists, and rejected request bodies are excluded from audit,
workflow state, checkpoints, logs, and traces. Telemetry remains
non-authoritative.

## Positive and negative authorization cases

Later implementation must automate at least these cases.

Positive:

1. configured service token admits an allowed synthetic event;
2. signed producer with a fresh nonce admits the same contract;
3. safe retry with a new signature nonce and unchanged idempotency key returns
   the original run;
4. same-scope reviewer reads a pending approval;
5. authorized reviewer decides the current hash/version once;
6. operator replays an eligible closed failure with a reason;
7. safety reviewer with both permissions releases quarantine;
8. observer reads metrics but cannot read runs.

Negative:

1. missing, expired, future, unsigned, wrong-algorithm, wrong-issuer,
   wrong-audience, wrong-type, or unknown-key JWT;
2. an ID token presented as an access token;
3. token exceeding the sample lifetime or clock-skew bound;
4. service token attempting human approval;
5. reviewer attempting event admission or operator replay;
6. correct permission with wrong resource scope, source, environment, or
   workflow;
7. body attempting to override trusted scope, source, workflow, actor, or role;
8. signature missing a covered component, with a changed body/digest, outside
   its time window, or using a repeated nonce;
9. retry reusing an idempotency key with a changed canonical fingerprint;
10. stale, altered, expired, unauthorized, or repeated approval;
11. normal operator attempting quarantine release;
12. out-of-scope object lookup leaking existence;
13. graph, model, or tool output attempting to add permissions;
14. unknown policy version or failed JWKS refresh silently failing open.

## Alternatives considered

### Disable authentication for the local demo

Rejected. A public sample should exercise the security boundary it expects
later code to preserve. Loopback binding and fixture tokens keep local use
practical without an insecure alternate code path.

### Static API keys or a shared HMAC JWT secret

Rejected. They blur principal identity, complicate rotation and audience
separation, and encourage copying secrets into configuration or source.

### JWT access tokens for every producer

Accepted as the preferred profile, but not required for webhook systems that
cannot obtain OAuth tokens. Those producers use an explicit signed-message
contract.

### Custom webhook HMAC headers

Rejected for the shared contract. HTTP Message Signatures and Content-Digest
make covered components, timestamps, nonces, key IDs, and content integrity
explicit. An external adapter may translate a provider-specific webhook only
after A07/C01 contract review; this API does not pretend custom schemes are
interchangeable.

### Trust roles and scope directly from token claims

Rejected. Claims are inputs from a trusted issuer but remain intersected with
local issuer/client, route, resource, and state policy. Token contents alone do
not authorize.

### Full policy engine or company directory in this repository

Rejected for the sample. Deterministic typed policy is sufficient and keeps
company identity ownership outside this public repository.

### Require mTLS or DPoP in the local sample

Deferred. OAuth security guidance recommends sender-constrained tokens, but
certificate/proof key lifecycle belongs to the deployment decision. Company
exposure cannot inherit the local bearer-token risk acceptance automatically.

## Consequences

### Benefits

- No unauthenticated implementation path can drift into a deployment.
- API, webhook, approval, and operator identities have explicit trust rules.
- Scope and workflow selection cannot be injected through event content.
- Durable nonce claims prevent signed-request replay across replicas/restarts.
- Approval decisions are bound to one exact interrupt and actor.
- Positive and negative authorization behavior is directly testable.

### Costs and risks

- JWT verification needs issuer metadata/JWKS caching and rotation tests.
- Signed HTTP messages require careful proxy URL canonicalization.
- Durable nonce claims add a small high-churn table and retention job.
- Bearer-token theft remains possible during the short validity window.
- The local principal fixture cannot validate company role/group governance.

## Deployment inputs resolved by A07

ADR-0005 and ADR-0006 resolve these inputs for the local public sample. Any
other deployment must name:

- trusted issuer, API audience, discovery/JWKS ownership, and rotation behavior;
- TLS termination and trusted-proxy canonical URL rules;
- whether signed webhook ingress is enabled and who owns producer keys;
- token acquisition flow and sender constraint/revocation strategy;
- policy configuration/release owner;
- internal exposure for readiness and metrics;
- secrets/certificate storage;
- rate limits and abuse controls.

Before company use, a new decision must also define team/resource mapping,
multi-tenant isolation, deprovisioning latency, privileged roles, separation of
duties, break glass, and security-event retention.

## Verification required by later tasks

- B03 tests JWT validation, key rotation, local fixture isolation, and every
  negative token case above.
- B05 tests route/resource authorization and non-disclosing object lookup.
- B06 tests signed components, digest, timestamps, nonce uniqueness, and safe
  idempotent retry.
- B13 tests approval identity, action hash, expiry, optimistic concurrency, and
  exactly one resume job.
- Resilience tests prove nonce/idempotency claims work across API replicas and
  process restart.
- Redaction tests prove credentials and raw identity tokens never enter state,
  audit, logs, traces, or errors.

## References

- [RFC 8725: JSON Web Token Best Current Practices](https://www.rfc-editor.org/rfc/rfc8725.html)
- [RFC 9068: JWT Profile for OAuth 2.0 Access Tokens](https://www.rfc-editor.org/rfc/rfc9068.html)
- [RFC 9700: Best Current Practice for OAuth 2.0 Security](https://www.rfc-editor.org/rfc/rfc9700.html)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0-18.html)
- [RFC 9421: HTTP Message Signatures](https://www.rfc-editor.org/rfc/rfc9421.html)
- [RFC 9530: Digest Fields](https://www.rfc-editor.org/rfc/rfc9530.html)
- [ADR-0002: PostgreSQL durable delivery](0002-postgres-durable-delivery.md)
- [ADR-0003: Persistence, checkpoints, and retention](0003-persistence-checkpoints-and-retention.md)
- [ADR-0005: Local Compose deployment](0005-local-compose-deployment.md)
- [ADR-0006: External adapter contracts](0006-external-adapter-contracts.md)
- [Repository architecture](../architecture.md)
