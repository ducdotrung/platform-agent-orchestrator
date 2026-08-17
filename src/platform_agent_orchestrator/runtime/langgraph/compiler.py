"""Compile framework flow definitions into internal LangGraph graphs."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, StateGraph

from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.sdk.flow import (
    FLOW_END,
    FlowDefinition,
    FlowTarget,
    NodeResult,
    NodeSpec,
)
from platform_agent_orchestrator.sdk.nodes import NodeContext, NodeOutcome, PauseExecution

from .interrupts import pause_execution

LangGraphNodeCallable = Callable[
    [dict[str, Any]],
    Awaitable[dict[str, Any]],
]


class LangGraphCompiler:
    """Translate the intentionally small framework graph specification."""

    def compile(
        self,
        definition: FlowDefinition,
        *,
        checkpointer: object | None,
        context: ExecutionContext,
    ) -> object:
        """Compile a definition without exposing the compiled implementation type."""

        self._validate(definition)
        graph = StateGraph(definition.state_schema)

        for node in definition.nodes:
            graph.add_node(node.name, self._wrap_handler(node, context))
        for edge in definition.edges:
            graph.add_edge(edge.source, self._target(edge.target))
        for join in definition.joins:
            graph.add_edge(list(join.sources), self._target(join.target))
        for route in definition.conditional_routes:
            graph.add_conditional_edges(
                route.source,
                route.router,
                {key: self._target(target) for key, target in route.routes.items()},
            )

        graph.set_entry_point(definition.entrypoint)
        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _target(target: FlowTarget) -> str:
        if target is FLOW_END:
            return END
        if isinstance(target, str):
            return target
        raise ValueError(f"unsupported flow target: {target!r}")

    @staticmethod
    def _wrap_handler(
        node: NodeSpec,
        execution: ExecutionContext,
    ) -> LangGraphNodeCallable:
        async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
            updates: dict[str, Any] = {}
            resume_payload: dict[str, Any] | None = None

            while True:
                node_context = NodeContext(
                    execution=execution,
                    node_name=node.name,
                    resume_payload=resume_payload,
                )
                try:
                    raw_outcome = node.handler(dict(state), node_context)
                    if inspect.isawaitable(raw_outcome):
                        raw_outcome = await raw_outcome
                    outcome = LangGraphCompiler._normalize_outcome(raw_outcome)
                except PauseExecution as paused:
                    outcome = NodeOutcome(pause=paused.request)

                updates.update(outcome.updates)
                if outcome.pause is None:
                    return updates
                resumed = pause_execution(outcome.pause, updates)
                if not isinstance(resumed, dict):
                    raise TypeError("pause resume payload must be a mapping")
                resume_payload = resumed

        return wrapped

    @staticmethod
    def _normalize_outcome(result: NodeResult) -> NodeOutcome:
        if isinstance(result, NodeOutcome):
            return result
        if isinstance(result, dict):
            return NodeOutcome(updates=result)
        raise TypeError("flow node must return dict or NodeOutcome")

    @staticmethod
    def _validate(definition: FlowDefinition) -> None:
        node_names = [node.name for node in definition.nodes]
        known = set(node_names)
        if len(known) != len(node_names):
            raise ValueError("flow definition contains duplicate node names")
        if definition.entrypoint not in known:
            raise ValueError("flow entrypoint must reference a registered node")

        has_terminal = False
        for edge in definition.edges:
            if edge.source not in known:
                raise ValueError(f"unknown edge source: {edge.source}")
            if edge.target is FLOW_END:
                has_terminal = True
            elif edge.target not in known:
                raise ValueError(f"unknown edge target: {edge.target}")
        for join in definition.joins:
            if len(join.sources) < 2:
                raise ValueError("flow join must contain at least two sources")
            if len(set(join.sources)) != len(join.sources):
                raise ValueError("flow join contains duplicate sources")
            unknown_sources = set(join.sources) - known
            if unknown_sources:
                raise ValueError(f"unknown join source: {sorted(unknown_sources)[0]}")
            if join.target is FLOW_END:
                has_terminal = True
            elif join.target not in known:
                raise ValueError(f"unknown join target: {join.target}")
        for route in definition.conditional_routes:
            if route.source not in known:
                raise ValueError(f"unknown conditional source: {route.source}")
            for target in route.routes.values():
                if target is FLOW_END:
                    has_terminal = True
                elif target not in known:
                    raise ValueError(f"unknown conditional target: {target}")
        if not has_terminal:
            raise ValueError("flow definition must explicitly target FLOW_END")
