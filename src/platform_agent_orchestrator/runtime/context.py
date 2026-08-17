"""Execution-context composition at the application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from platform_agent_orchestrator.core.context import ExecutionContext, ExecutionIdentity
from platform_agent_orchestrator.core.events import DomainEvent
from platform_agent_orchestrator.sdk.flow import Flow

from .execution import RunMetadata


@dataclass(frozen=True)
class ExecutionContextFactory:
    """Build runtime contexts from new or durably reconstructed identities."""

    capabilities: object
    agents: object
    policy: object
    observability: object

    def create(self, event: DomainEvent, flow: Flow) -> ExecutionContext:
        run_id = str(uuid4())
        return self._context(
            identity=ExecutionIdentity(
                run_id=run_id,
                thread_id=run_id,
                correlation_id=event.correlation_id,
                tenant_id=event.tenant_id,
            ),
            flow=flow,
        )

    def restore(self, run: RunMetadata, flow: Flow) -> ExecutionContext:
        return self._context(
            identity=ExecutionIdentity(
                run_id=run.run_id,
                thread_id=run.thread_id,
                correlation_id=run.correlation_id,
                tenant_id=run.tenant_id,
            ),
            flow=flow,
        )

    def _context(self, *, identity: ExecutionIdentity, flow: Flow) -> ExecutionContext:
        return ExecutionContext(
            identity=identity,
            capabilities=self.capabilities,
            agents=self.agents,
            policy=self.policy,
            observability=self.observability,
            metadata={
                "flow_name": flow.metadata.name,
                "flow_version": flow.metadata.version,
            },
        )
