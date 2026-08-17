"""LangGraph implementation of the generic workflow runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from platform_agent_orchestrator.core.context import ExecutionContext, ExecutionIdentity
from platform_agent_orchestrator.core.events import DomainEvent
from platform_agent_orchestrator.runtime.execution import RunResult, RunStatus
from platform_agent_orchestrator.sdk.flow import Flow

from .checkpoint import LangGraphCheckpoint
from .compiler import LangGraphCompiler
from .interrupts import INTERRUPT_RESULT_KEY, extract_pause, resume_command


@dataclass(frozen=True)
class _RunMetadata:
    flow: Flow
    identity: ExecutionIdentity


class LangGraphWorkflowRuntime:
    """Start and resume framework flows using the default runtime adapter."""

    def __init__(
        self,
        *,
        compiler: LangGraphCompiler | None = None,
        checkpointer: object | None = None,
    ) -> None:
        self._compiler = compiler or LangGraphCompiler()
        self._checkpoint = (
            LangGraphCheckpoint()
            if checkpointer is None
            else LangGraphCheckpoint(checkpointer)
        )
        # Convenience cache for same-process callers. Durable application metadata
        # plus a registry-resolved flow is the authoritative restart/resume input.
        self._active_runs: dict[str, _RunMetadata] = {}

    async def start(
        self,
        flow: Flow,
        event: DomainEvent,
        *,
        context: ExecutionContext,
    ) -> RunResult:
        run_id = context.identity.run_id
        flow_name = flow.metadata.name
        if run_id in self._active_runs:
            return RunResult(
                run_id=run_id,
                flow=flow_name,
                status=RunStatus.FAILED,
                error="run_id is already registered",
            )

        initial_state = {
            "event": event.model_dump(mode="json"),
            "run_id": run_id,
        }
        try:
            graph = self._compiler.compile(
                flow.define(),
                checkpointer=self._checkpoint.saver,
                context=context,
            )
            self._active_runs[run_id] = _RunMetadata(flow=flow, identity=context.identity)
            result = await graph.ainvoke(
                initial_state,
                config=self._checkpoint.config(context.identity.thread_id),
            )
            run_result = self._result(run_id, flow_name, result)
            if run_result.status is not RunStatus.PAUSED:
                self._active_runs.pop(run_id, None)
            return run_result
        except Exception as error:
            self._active_runs.pop(run_id, None)
            return self._failed(run_id, flow_name, error)

    async def resume(
        self,
        run_id: str,
        payload: dict[str, Any],
        *,
        context: ExecutionContext,
        flow: Flow | None = None,
    ) -> RunResult:
        metadata = self._active_runs.get(run_id)
        selected_flow = flow or (metadata.flow if metadata is not None else None)
        if selected_flow is None:
            return RunResult(
                run_id=run_id,
                flow="unknown",
                status=RunStatus.FAILED,
                error="run_id is not registered",
            )
        flow_name = selected_flow.metadata.name
        if context.identity.run_id != run_id:
            return RunResult(
                run_id=run_id,
                flow=flow_name,
                status=RunStatus.FAILED,
                error="resume context run_id does not match the requested run",
            )
        if metadata is not None and context.identity != metadata.identity:
            return RunResult(
                run_id=run_id,
                flow=flow_name,
                status=RunStatus.FAILED,
                error="resume identity does not match the paused run",
            )
        if metadata is not None and (
            metadata.flow.metadata.name != selected_flow.metadata.name
            or metadata.flow.metadata.version != selected_flow.metadata.version
        ):
            return RunResult(
                run_id=run_id,
                flow=flow_name,
                status=RunStatus.FAILED,
                error="resume flow does not match the paused run",
            )

        try:
            graph = self._compiler.compile(
                selected_flow.define(),
                checkpointer=self._checkpoint.saver,
                context=context,
            )
            result = await graph.ainvoke(
                resume_command(payload),
                config=self._checkpoint.config(context.identity.thread_id),
            )
            run_result = self._result(run_id, flow_name, result)
            if run_result.status is not RunStatus.PAUSED:
                self._active_runs.pop(run_id, None)
            return run_result
        except Exception as error:
            return self._failed(run_id, flow_name, error)

    @staticmethod
    def _result(run_id: str, flow_name: str, raw: object) -> RunResult:
        if not isinstance(raw, dict):
            return RunResult(
                run_id=run_id,
                flow=flow_name,
                status=RunStatus.FAILED,
                error="runtime returned a non-mapping result",
            )
        pause, prospective_updates = extract_pause(raw)
        output = {key: value for key, value in raw.items() if key != INTERRUPT_RESULT_KEY}
        output.update(prospective_updates)
        return RunResult(
            run_id=run_id,
            flow=flow_name,
            status=RunStatus.PAUSED if pause is not None else RunStatus.SUCCEEDED,
            output=output,
            pause=pause,
        )

    @staticmethod
    def _failed(run_id: str, flow_name: str, error: Exception) -> RunResult:
        return RunResult(
            run_id=run_id,
            flow=flow_name,
            status=RunStatus.FAILED,
            error=f"{type(error).__name__}: {error}",
        )
