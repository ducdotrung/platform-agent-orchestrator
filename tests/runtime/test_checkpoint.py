from __future__ import annotations

import pytest

from platform_agent_orchestrator.runtime.langgraph import LangGraphCheckpoint


def test_checkpoint_wrapper_owns_saver_and_validates_thread_identity() -> None:
    checkpoint = LangGraphCheckpoint()

    assert checkpoint.saver is not None
    assert checkpoint.config("run-1") == {"configurable": {"thread_id": "run-1"}}

    with pytest.raises(ValueError):
        checkpoint.config(" padded ")
