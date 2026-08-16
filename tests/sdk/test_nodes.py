from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.sdk import NodeOutcome, PauseExecution, PauseRequest


def test_node_outcome_carries_runtime_neutral_pause_request() -> None:
    pause = PauseRequest(
        reason="Review low-confidence recommendation",
        approval_id="approval-1",
        payload={"confidence": 0.42},
    )
    outcome = NodeOutcome(updates={"status": "review"}, pause=pause)

    assert outcome.pause == pause
    assert outcome.model_dump(mode="json")["pause"]["approval_id"] == "approval-1"


def test_pause_request_requires_stable_approval_identity() -> None:
    with pytest.raises(ValidationError):
        PauseRequest(reason="Review", approval_id="")


def test_pause_exception_preserves_the_framework_request() -> None:
    pause = PauseRequest(reason="Review", approval_id="approval-1")

    with pytest.raises(PauseExecution) as raised:
        raise PauseExecution(pause)

    assert raised.value.request == pause
