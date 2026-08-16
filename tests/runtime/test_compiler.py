from __future__ import annotations

import pytest

from platform_agent_orchestrator.runtime.langgraph import (
    LangGraphCheckpoint,
    LangGraphCompiler,
)
from platform_agent_orchestrator.sdk import EdgeSpec, FlowDefinition, NodeSpec

from .helpers import context


def _noop(state: dict[str, object], _context: object) -> dict[str, object]:
    return state


def test_compiler_rejects_magic_terminal_target() -> None:
    flow = FlowDefinition(
        state_schema=dict,
        entrypoint="start",
        nodes=[NodeSpec(name="start", handler=_noop)],
        edges=[EdgeSpec(source="start", target="done")],
    )

    with pytest.raises(ValueError, match="unknown edge target"):
        LangGraphCompiler().compile(
            flow,
            context=context(),
            checkpointer=LangGraphCheckpoint().saver,
        )


def test_compiler_requires_framework_terminal_sentinel() -> None:
    flow = FlowDefinition(
        state_schema=dict,
        entrypoint="start",
        nodes=[NodeSpec(name="start", handler=_noop)],
        edges=[EdgeSpec(source="start", target="start")],
    )

    with pytest.raises(ValueError, match="FLOW_END"):
        LangGraphCompiler().compile(
            flow,
            context=context(),
            checkpointer=LangGraphCheckpoint().saver,
        )
