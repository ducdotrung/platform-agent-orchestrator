"""Workflow lookup and event-type validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from platform_agent_orchestrator.adapters.ports import PlatformServices
from platform_agent_orchestrator.contracts import DomainEvent, EventType
from platform_agent_orchestrator.observability import NoOpObservability, ObservabilityBackend
from platform_agent_orchestrator.observability.base import ScoreDataType, ScoreValue, WorkflowTrace
from platform_agent_orchestrator.workflows import (
    build_alert_graph,
    build_engineering_graph,
    build_knowledge_refresh_graph,
    build_sre_execution_graph,
)

WORKFLOW_EVENT_TYPES = {
    "alert": EventType.ALERT_RECEIVED,
    "refresh": EventType.PR_MERGED,
    "sre": EventType.SRE_TICKET_UPDATED,
    "engineering": EventType.ENGINEERING_QUESTION,
}


@dataclass
class WorkflowRegistry:
    services: PlatformServices
    checkpointer: Any | None = None
    observability: ObservabilityBackend = field(default_factory=NoOpObservability)

    def build(self, workflow: str) -> Any:
        factories = {
            "alert": build_alert_graph,
            "refresh": build_knowledge_refresh_graph,
            "sre": build_sre_execution_graph,
            "engineering": build_engineering_graph,
        }
        try:
            factory = factories[workflow]
        except KeyError as exc:
            raise ValueError(f"Unknown workflow: {workflow}") from exc
        return factory(self.services, checkpointer=self.checkpointer)

    def invoke(
        self,
        workflow: str,
        event: DomainEvent,
        *,
        thread_id: str | None = None,
        extra_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        expected = WORKFLOW_EVENT_TYPES.get(workflow)
        if expected is None:
            raise ValueError(f"Unknown workflow: {workflow}")
        if event.type != expected:
            raise ValueError(f"Workflow {workflow!r} expects {expected}, received {event.type}")
        state = {"event": event.model_dump(mode="json"), **(extra_state or {})}
        with self.observability.trace_workflow(workflow, event) as trace:
            config = {
                "configurable": {"thread_id": thread_id or event.correlation_id},
                "callbacks": trace.callbacks,
                "tags": trace.tags,
                "metadata": trace.metadata,
            }
            try:
                result = self.build(workflow).invoke(state, config=config)
            except BaseException as error:
                trace.fail(error)
                raise
            trace.complete(result)
            self._record_outcome_scores(trace, result)
            return result

    def score_trace(
        self,
        trace_id: str,
        name: str,
        value: ScoreValue,
        *,
        data_type: ScoreDataType | None = None,
        comment: str | None = None,
    ) -> None:
        """Attach delayed human or automated feedback to an existing trace."""

        self.observability.score(
            trace_id,
            name,
            value,
            data_type=data_type,
            comment=comment,
        )

    @staticmethod
    def _record_outcome_scores(trace: WorkflowTrace, result: dict[str, Any]) -> None:
        decision = result.get("decision")
        if isinstance(decision, dict):
            confidence = decision.get("confidence")
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                trace.score("decision.confidence", float(confidence), data_type="NUMERIC")
        if isinstance(result.get("verified"), bool):
            trace.score("action.verified", result["verified"], data_type="BOOLEAN")
        if "validation_errors" in result:
            trace.score(
                "knowledge.validation_passed",
                not bool(result["validation_errors"]),
                data_type="BOOLEAN",
            )
