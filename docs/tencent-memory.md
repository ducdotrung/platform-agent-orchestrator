# TencentDB Agent Memory adapter

TencentDB Agent Memory is an optional `MemoryPort` implementation. The default/demo
composition remains credential-free and continues to register `DemoMemory`.

Install the optional HTTP dependency:

```bash
pip install 'platform-agent-orchestrator[tencent-memory]'
```

Configure the adapter at the process boundary. Do not put these values in events,
workflow state, checkpoints, or telemetry:

```text
TENCENT_MEMORY_ENABLED=true
TENCENT_MEMORY_ENDPOINT=https://memory.tdai.tencentyun.com
TENCENT_MEMORY_API_KEY=<secret>
TENCENT_MEMORY_SERVICE_ID=<instance-id>
TENCENT_MEMORY_AGENT_ID=platform-agent-orchestrator
TENCENT_MEMORY_USER_ID=platform-agent-orchestrator
TENCENT_MEMORY_DEFAULT_TEAM_ID=default
```

Compose it through the existing generic capability provider:

```python
from platform_agent_orchestrator.adapters.memory import MemoryCapabilityProvider
from platform_agent_orchestrator.adapters.tencent_memory import (
    HttpTencentMemoryClient,
    TencentMemoryAdapter,
    TencentMemorySettings,
)

settings = TencentMemorySettings.from_env()
client = HttpTencentMemoryClient(settings)
memory = TencentMemoryAdapter(client=client, settings=settings)
capabilities.register(MemoryCapabilityProvider(memory))
```

The application owns `client` and must call `await client.aclose()` during shutdown.
The adapter maps framework `tenant_id` to Tencent `team_id`, its configured agent/user
identity to Tencent ownership, and framework scope to a Tencent session. Framework
metadata is encoded in a versioned conversation envelope. Sensitive metadata keys and
common bearer/API-key patterns are redacted before transmission and after recall.

The wire client follows Tencent's documented V3 HTTPS JSON endpoints and authentication:

- [V3 request and authentication format](https://cloud.tencent.com/document/product/1813/135146)
- [V3 SDK and isolation model](https://cloud.tencent.com/document/product/1813/135117)
- [V3 API hierarchy](https://cloud.tencent.com/document/product/1813/132001)

## Idempotency limitation

The documented V3 `conversation/add` API does not expose a native idempotency key. The
adapter therefore serializes writes in-process, caches successful receipts, and scans
the isolated remote session for a matching versioned idempotency marker before each
uncached write. It fails closed when the configured scan limit cannot prove that a write
is new, and rejects reuse of a key with different content.

This prevents ordinary retries and restart retries from duplicating a record. It cannot
atomically prevent two different processes from racing on the first write because the
remote query and add operations are separate. Deployments with concurrent writers for
the same tenant/scope must serialize those writes through one worker or add a durable
shared idempotency guard outside this adapter.

Recall failures are returned as explicit failed capability results. Builtin flows may
degrade only because their memory capabilities are already optional. Record and feedback
failures are also explicit and are never reported as successful writes.
