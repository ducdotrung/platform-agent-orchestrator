# Langfuse observability

Langfuse is an optional telemetry and evaluation layer. LangGraph remains the
workflow runtime and checkpoint source of truth; Langfuse is not used for
workflow recovery, authorization, or durable audit records.

## Enable it

Install the optional dependency and configure credentials:

```bash
pip install -e '.[observability]'
export PLATFORM_OBSERVABILITY=langfuse
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
# Only for self-hosted Langfuse:
export LANGFUSE_BASE_URL=https://langfuse.example.com
python -m platform_agent_orchestrator demo all
```

The CLI calls `shutdown()` before exit so buffered spans are delivered. A
long-lived worker should reuse one backend instance and call `shutdown()`
during graceful termination.

## Trace model

When an application integration opens a workflow trace, the backend creates one
`workflow.<name>` root observation using the native Langfuse observation context.
It does not inject agent-framework callbacks into graph invocation. The event
correlation ID becomes a Langfuse session ID, so retries and human-review resumes
can be examined together without forcing them to share one trace ID.

Exported root metadata is intentionally bounded to workflow and event
identifiers. Domain event payloads, idempotency keys, evidence bodies,
artifacts, credentials, and full checkpoint state are excluded.

## Data controls

`PLATFORM_TRACE_CAPTURE_CONTENT=false` is the safe default. It removes prompt,
completion, message, tool argument, tool result, input, and output attributes
from the OpenTelemetry batch. Remaining strings are masked for common
credentials, JWTs, bearer tokens, email addresses, and sensitive structured
keys. Set content capture to `true` only after reviewing classification,
retention, and access policy; masking still applies.

Use `LANGFUSE_SAMPLE_RATE` between `0` and `1` for production sampling. Keep
security and audit events in their dedicated stores because sampled telemetry
cannot prove that an action did or did not occur.

## Evaluation

The registry records deterministic scores when a workflow exposes them:

- `decision.confidence` for structured alert decisions;
- `action.verified` for SRE execution verification;
- `knowledge.validation_passed` for refresh validation.

Delayed QA, operator, or product feedback can be attached by trace ID:

```python
registry.score_trace(
    trace_id,
    "human.correctness",
    True,
    data_type="BOOLEAN",
    comment="Recommendation matched the incident review",
)
```

Do not treat model confidence as correctness. Use replay datasets and human
feedback to compare prompt, model, policy, and workflow releases over time.
