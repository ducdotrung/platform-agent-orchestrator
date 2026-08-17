# Platform Agent Orchestrator

A runtime-neutral orchestration framework for building pluggable AI agent workflows.

Platform Agent Orchestrator provides a small set of framework-owned contracts for composing agents, capabilities, policies, memory, human approval, and workflow runtimes without coupling application code to a specific agent framework or orchestration engine.

LangGraph is currently supported as a runtime backend, but it is not part of the public workflow contract.

The repository also includes reference workflows for engineering assistance, knowledge refresh, alert analysis, and SRE automation. These are examples of how the framework can be used — they are not the scope of the framework itself.

> **Status:** active development. The project is currently a reference implementation and is not yet intended for production use.

## Why

Agent systems often start as a single graph or agent and gradually accumulate:

- framework-specific workflow code;
- direct integrations with external systems;
- duplicated tool and capability definitions;
- workflow-specific policy logic;
- provider-specific memory implementations;
- tightly coupled human-in-the-loop handling.

That makes workflows difficult to reuse, test, replace, or distribute independently.

Platform Agent Orchestrator separates these concerns.

```text
                    DomainEvent
                         |
                         v
                +----------------+
                |   Dispatcher   |
                +----------------+
                         |
                         v
                  Flow Registry
                         |
              +----------+----------+
              |                     |
              v                     v
        FlowDefinition         FlowDefinition
              |                     |
              +----------+----------+
                         |
                         v
                  WorkflowRuntime
                         |
               +---------+---------+
               |                   |
               v                   v
          LangGraph            future runtime
           adapter               adapters


        Flows / Agents
              |
              v
     Capability Registry
              |
     +--------+--------+--------+
     |        |        |        |
 knowledge  memory   actions  notifications
     |        |        |        |
     v        v        v        v
 external providers / APIs / MCP / services
```

The framework owns the contracts.

Plugins own workflow composition.

Capability providers own integrations.

Runtime adapters own orchestration-engine-specific behavior.

## Design principles

### Runtime-neutral workflows

Application workflows are defined using framework-owned contracts such as:

- `Flow`
- `FlowDefinition`
- `NodeSpec`
- `EdgeSpec`
- `JoinSpec`
- `FLOW_END`
- `PauseRequest`

Flows do not expose LangGraph `StateGraph`, `CompiledGraph`, `Command`, `interrupt`, or other runtime-specific types.

Runtime-specific translation belongs under `runtime/`.

### Pluggable workflows

Flows are registered dynamically instead of being hard-coded into the orchestrator.

An event may match zero, one, or multiple flows.

Plugins can contribute:

- flows;
- agents;
- capabilities;
- metadata;
- permissions.

The goal is for independently distributed Python packages to be able to extend the orchestrator without modifying its core.

### Capability-based integrations

Flows depend on capabilities rather than concrete integrations.

For example:

```text
knowledge.search
knowledge.publish
memory.recall
memory.record
memory.feedback
notification.send
alert.classify
```

A flow does not need to know whether `knowledge.search` is implemented by a graph database, MCP server, REST API, local index, or another service.

Providers can therefore be replaced without changing workflow definitions.

### Provider-neutral agents

Agents implement framework-owned request/response contracts.

Flows resolve agents through the agent registry rather than constructing provider-specific agent implementations directly.

This keeps LLM providers and agent libraries outside the workflow contract.

### Policy before mutation

External mutations are represented as `ActionIntent`.

The intended execution path is:

```text
ActionIntent
     |
     v
PolicyEngine
     |
     +---- deny
     |
     +---- allow -----------> execute
     |
     +---- require approval
                |
                v
           PauseRequest
                |
          human decision
                |
                v
              resume
                |
                v
              execute
```

Approval is bound to the exact action, execution identity, and policy version so that an approval cannot silently authorize a modified action.

### Memory is infrastructure, not workflow ownership

Workflows may request capabilities such as:

```text
memory.recall
memory.record
memory.feedback
```

but should not depend directly on a particular memory database.

Memory providers belong behind framework ports/capabilities and can be replaced independently.

### Durable execution

The service runtime supports durable event admission and execution metadata.

Durable runs retain framework-level identity such as:

```text
run_id
flow_name
flow_version
thread_id
correlation_id
tenant_id
status
```

Runtime objects and compiled graphs are not application persistence contracts.

This allows workflow execution infrastructure to evolve independently from application persistence.

## Architecture

The main layers are:

```text
platform_agent_orchestrator/
├── core/                 # framework-owned domain contracts
├── sdk/                  # public flow/agent/plugin SDK
├── registry/             # flow, agent, capability registries
├── policy/               # risk and approval policy
├── runtime/
│   └── langgraph/        # LangGraph runtime adapter
├── plugins/
│   └── builtin/          # reference workflow plugins
├── adapters/             # integration implementations
├── persistence/          # durable application state
└── ...
```

The intended dependency direction is roughly:

```text
plugins
   |
   v
SDK / Core
   ^
   |
registries / runtime / adapters
```

Framework-neutral contracts must not depend on runtime implementations.

## Reference workflows

The repository currently includes several workflows that exercise different orchestration patterns.

They are reference implementations, not framework requirements.

### Engineering assistance

Demonstrates:

- agent registry;
- role-based agent routing;
- required and optional capabilities;
- evidence-backed answers;
- optional memory retrieval.

Example roles include developer, QA, and business-analysis agents.

### Knowledge refresh

Demonstrates:

- event-driven workflows;
- parallel fan-out;
- fan-in barriers;
- provenance validation;
- atomic publication;
- idempotent side effects;
- selective memory recording.

A merged source-control event can trigger code, configuration, and documentation extraction concurrently before a revisioned knowledge snapshot is published.

### Alert analysis

Demonstrates the integration of domain-specific alert classification with shared knowledge, impact analysis, review, notification, and memory capabilities.

Alert policy remains owned by the alert provider rather than being copied into the orchestrator.

### SRE automation

Demonstrates controlled mutation workflows:

```text
plan
  ↓
ActionIntent
  ↓
policy
  ↓
approval?
  ↓
execute
  ↓
verify
```

Infrastructure actions remain behind bounded capability providers rather than exposing arbitrary shell execution to workflows.

## Runtime backends

### LangGraph

LangGraph is the first runtime backend.

The adapter is responsible for translating framework semantics such as:

```text
FlowDefinition  -> StateGraph
FLOW_END        -> LangGraph END
PauseRequest    -> interrupt()
resume payload  -> Command(resume=...)
```

This translation is intentionally isolated under:

```text
runtime/langgraph/
```

Plugins and public SDK contracts should not import LangGraph.

The architecture is intended to allow additional runtime implementations in the future.

## Plugin model

A plugin can register flows, agents, and capabilities through the public SDK.

Conceptually:

```python
class MyPlugin:
    def register(self, context):
        context.agents.register(...)
        context.capabilities.register(...)
        context.flows.register(...)
```

A workflow package should depend on capabilities rather than concrete infrastructure.

For example:

```text
customer-support
    |
    +-- crm.customer.lookup
    +-- knowledge.search
    +-- ticket.create
    +-- memory.recall
    +-- notification.send
```

The orchestrator itself does not need customer-support-specific logic.

The same model can be used for domains such as:

- customer support;
- security review;
- incident response;
- FinOps;
- release management;
- data analysis;
- engineering assistance;
- operations automation.

## Adding an integration

Implement a capability provider rather than importing an integration directly into a workflow.

For example:

```python
class MyKnowledgeProvider:
    @property
    def capabilities(self):
        return {"knowledge.search"}

    async def invoke(self, request):
        ...
```

Then register the provider with the capability registry.

Flows can now request `knowledge.search` without knowing which implementation serves it.

This pattern also applies to:

```text
memory.*
notification.*
scm.*
ticket.*
deployment.*
infrastructure.*
alert.*
```

## Human-in-the-loop

Human approval is represented using framework-owned pause/resume contracts.

Plugins do not call LangGraph `interrupt()` directly.

Instead they return a framework `PauseRequest`.

The active runtime translates that request into its own suspension mechanism.

This allows approval semantics to remain stable even if the workflow runtime changes.

External side effects should be idempotent because execution may be retried during recovery.

## Quick start

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
. .venv/bin/activate

pip install -e '.[dev]'

python -m platform_agent_orchestrator demo all

pytest
```

Individual reference workflows:

```bash
python -m platform_agent_orchestrator demo alert
python -m platform_agent_orchestrator demo refresh
python -m platform_agent_orchestrator demo sre
python -m platform_agent_orchestrator demo engineering
```

The default demo profile uses deterministic local providers and does not require external API credentials.

## Local durable stack

A loopback-only Compose stack is available for exercising durable admission, PostgreSQL persistence, checkpointing, API execution, and workers.

```bash
python deploy/generate_secrets.py

docker compose up --build --detach --wait api worker

PYTHONPATH=src python deploy/smoke.py
```

Useful endpoints:

```text
/livez
/readyz
/metrics
```

Normal teardown preserves the database volume:

```bash
docker compose down
```

Delete disposable data explicitly with:

```bash
docker compose down --volumes
```

## External systems

The orchestrator is intentionally not the owner of every domain implementation.

External systems may provide capabilities through APIs, MCP servers, Python adapters, or other transports.

Examples used by the reference implementation include separate systems for:

- service/code knowledge;
- alert classification;
- SRE actions;
- documentation/wiki presentation;
- memory storage.

The orchestrator coordinates these capabilities but should not duplicate their domain logic.

## What belongs here?

The orchestrator should own:

```text
workflow contracts
plugin contracts
agent contracts
capability contracts
registries
dispatch
runtime abstraction
policy orchestration
approval semantics
execution identity
durable workflow coordination
```

Domain providers should own:

```text
alert classification rules
source-code graph extraction
infrastructure commands
ticket-system behavior
notification transports
memory storage
wiki/UI implementation
LLM provider integration
```

This boundary is intentional.

## Project status

The project is currently under active architectural migration toward the runtime-neutral plugin model.

All builtin workflows use the runtime-neutral v2 plugin contracts. Agents implement the public Agent SDK directly, so model providers can be integrated without coupling core or SDK types to an agent framework.

The target architecture is:

```text
                 Platform Agent Orchestrator

                   runtime-neutral core
                           |
          +----------------+----------------+
          |                |                |
       plugins         capabilities       policy
          |                |                |
          +----------------+----------------+
                           |
                     runtime API
                           |
              +------------+------------+
              |                         |
          LangGraph                 future runtime
```

The long-term goal is not to build a collection of hard-coded SRE agents.

The goal is to provide a reusable orchestration layer on which independently developed agent workflows can run.

## Development

Run the test suite:

```bash
pytest
```

Run linting:

```bash
ruff check .
```

The repository has no direct LangChain agent-framework dependency. Dependency-boundary tests keep the current LangGraph implementation confined to `runtime/langgraph` and prevent runtime-specific types from leaking into framework-neutral `core` and `sdk` contracts.

## Documentation

See:

- `docs/architecture.md` for architecture and ownership boundaries;
- `docs/observability.md` for tracing and evaluation;
- `docs/persistence.md` for durable execution;
- `docs/tencent-memory.md` for optional TencentDB Agent Memory configuration;
- `docs/adr/` for architecture decisions;
- `docs/security/` for threat models and security boundaries.

## License

See the repository license for usage and distribution terms.
