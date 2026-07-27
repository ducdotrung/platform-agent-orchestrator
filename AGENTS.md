# Repository operating rules

This repository owns cross-domain orchestration and shared contracts only.

- Keep source indexing in `service-graph-toolkit`.
- Keep alert policy and delivery logic in `sre-alert-agent`.
- Keep SRE playbooks and safety knowledge in `sre-skills`.
- Keep the user-facing wiki in `code-atlas-workbench`.
- Prefer deterministic nodes for parsing, validation, routing, and policy.
- Use an LLM only where semantic judgment is required.
- Require evidence for claims and explicit approval for risky mutations.
- Make every external side effect idempotent.
- Never place credentials, complete source corpora, or secret tool output in
  workflow state.
- Treat observability as telemetry, not as workflow state or an audit ledger.
- Keep trace content disabled by default and redact before telemetry export.
