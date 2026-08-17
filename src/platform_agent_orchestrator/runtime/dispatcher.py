"""Resolve events through flow registries and execute via WorkflowRuntime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from platform_agent_orchestrator.core.events import DomainEvent
from platform_agent_orchestrator.registry.flow import FlowRegistry
from platform_agent_orchestrator.sdk.flow import Flow

from .context import ExecutionContextFactory
from .engine import WorkflowRuntime
from .execution import RunMetadata, RunResult


class FlowVersionMismatch(ValueError):
    """A durable run references a different registered flow version."""


@dataclass(frozen=True)
class Dispatcher:
    flows: FlowRegistry
    runtime: WorkflowRuntime
    contexts: ExecutionContextFactory

    async def dispatch(self, event: DomainEvent) -> list[RunResult]:
        """Start every compatible registered flow in registration order."""

        results: list[RunResult] = []
        for flow in self.flows.resolve(event):
            context = self.contexts.create(event, flow)
            results.append(await self.runtime.start(flow, event, context=context))
        return results

    async def execute(self, run: RunMetadata, event: DomainEvent) -> RunResult:
        """Execute the flow bound to an already durable delivery run."""

        flow = self._resolve_durable_flow(run)
        if flow not in self.flows.resolve(event):
            raise ValueError("durable run flow no longer accepts its admitted event")
        context = self.contexts.restore(run, flow)
        return await self.runtime.start(flow, event, context=context)

    async def resume(
        self,
        run: RunMetadata,
        payload: dict[str, Any],
    ) -> RunResult:
        """Resume using only durable identity plus a registry-resolved flow."""

        flow = self._resolve_durable_flow(run)
        context = self.contexts.restore(run, flow)
        return await self.runtime.resume(
            run.run_id,
            payload,
            context=context,
            flow=flow,
        )

    def _resolve_durable_flow(self, run: RunMetadata) -> Flow:
        flow = self.flows.get(run.flow_name)
        if flow.metadata.version != run.flow_version:
            raise FlowVersionMismatch(
                f"run requires {run.flow_name}@{run.flow_version}, "
                f"registered version is {flow.metadata.version}"
            )
        return flow
