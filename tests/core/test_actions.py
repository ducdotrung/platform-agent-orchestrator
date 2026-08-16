from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.core import ActionIntent, ActionResult, RiskLevel


def test_action_intent_serializes_namespaced_capability_and_risk() -> None:
    intent = ActionIntent(
        capability="infra.inspect",
        operation="describe",
        resource="service/orders",
        requested_risk=RiskLevel.READ_ONLY,
        idempotency_key="inspect:orders:1",
    )

    assert intent.model_dump(mode="json") == {
        "capability": "infra.inspect",
        "operation": "describe",
        "resource": "service/orders",
        "arguments": {},
        "requested_risk": "read_only",
        "idempotency_key": "inspect:orders:1",
        "metadata": {},
    }


def test_action_intent_requires_an_idempotency_key() -> None:
    with pytest.raises(ValidationError):
        ActionIntent(
            capability="infra.execute",
            operation="restart",
            idempotency_key="",
        )


def test_action_result_keeps_provider_output_bounded_to_the_contract() -> None:
    result = ActionResult(success=False, status="failed", error="provider unavailable")

    assert result.output == {}
    assert result.error == "provider unavailable"
