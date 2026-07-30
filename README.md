# Platform Agent Orchestrator

A runnable reference control plane for coordinating the existing SRE, service
graph, Code Atlas, Jira, and alert capabilities without copying their domain
logic into one repository.

The current productization path is a public, local-only hackathon sample using
synthetic alerts and Sock Shop microservice evidence. Its personas, baseline,
and targets are illustrative; company adoption requires fresh discovery,
measured baselines, security review, and approval.

The sample uses:

- **LangGraph** for workflow state, routing, parallel work, checkpointing, and
  human approval;
- **LangChain** for optional tool-using role agents inside graph nodes;
- **Langfuse** as an optional, redacted tracing and evaluation backend;
- ports/adapters so GitNexus, Code Atlas, Sentry, Jira, Bitbucket, Teams, and
  MCP integrations can remain independently deployed;
- deterministic demo adapters, so the examples and tests do not need API keys.

## Architecture

```text
Bitbucket / Jira / Sentry / user questions
                    |
                    v
              DomainEvent
                    |
                    v
       +---------------------------+
       | LangGraph workflow registry|
       +---------------------------+
          |       |       |       |
          v       v       v       v
       refresh  alert    SRE   engineering
          |       |       |       |
          +-------+-------+-------+
                    |
        ports: knowledge, actions,
        publication, notification
                    |
       existing repos / MCP / APIs
```

The repository deliberately does not own source cloning, graph extraction,
alert policy files, infrastructure commands, or the wiki UI.

## Quick start

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python -m platform_agent_orchestrator demo all
pytest
```

To include Langfuse support, install `pip install -e '.[dev,observability]'`,
copy the relevant values from `.env.example`, and set
`PLATFORM_OBSERVABILITY=langfuse`. It is a no-op by default and requires no
credentials for local demos.

Individual demos:

```bash
python -m platform_agent_orchestrator demo alert
python -m platform_agent_orchestrator demo refresh
python -m platform_agent_orchestrator demo sre
python -m platform_agent_orchestrator demo engineering
```

## Workflows

### Alert analysis

Normalizes an alert, applies deterministic suppression and priority rules,
retrieves service knowledge, makes an impact decision, optionally pauses for
review, creates a recommendation, and emits a deduplicated notification.

### Knowledge refresh

Processes a merged-PR event, determines which knowledge surfaces changed,
runs code/config/document extraction branches in parallel, validates
provenance, and atomically publishes a revisioned snapshot.

### SRE execution

Builds a ticket plan, classifies its risk, pauses before risky execution,
invokes a bounded action port, verifies the result, and records an audit
notification.

### Engineering assistance

Routes developer, QA, and product/BA questions to role-specific reasoning over
the same evidence-backed knowledge plane.

## Adding real integrations

Implement the protocols in `adapters/ports.py`. Recommended first adapters:

1. `ServiceGraphKnowledgePort`: call the read-only MCP server in
   `service-graph-toolkit`.
2. `AlertNotificationPort`: call the existing Teams sender in
   `sre-alert-agent`.
3. `KnowledgePublisherPort`: publish revisioned graph artifacts for Code Atlas.
4. `SREActionPort`: expose allow-listed operations from `sre-skills`; never
   expose arbitrary shell execution.

Keep adapter credentials outside graph state. Graph checkpoints should contain
identifiers and results, not tokens or full source corpora.

## Human approval

The SRE and alert graphs use LangGraph `interrupt()`. Production callers must
compile with a durable checkpointer, pass a stable `thread_id`, and resume with
`Command(resume=...)`. External side effects use idempotency keys because a
node may be executed again after recovery.

See [docs/architecture.md](docs/architecture.md) for contracts, ownership, and
the suggested migration sequence. See
[docs/observability.md](docs/observability.md) for Langfuse configuration,
masking, sampling, and evaluation guidance. The
[production productization plan](docs/production-productization-plan.md) and
[reviewed execution backlog](docs/production-productization-review.md) describe
the gated path from the reference implementation to a read-only alert pilot.
