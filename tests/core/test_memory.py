from __future__ import annotations

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.core import MemoryItem, MemoryQuery, MemoryRecord


def test_memory_models_are_bounded_and_provider_neutral() -> None:
    query = MemoryQuery(
        query="orders rollback",
        scope="sre/orders/prod",
        limit=5,
        filters={"kind": "operational_outcome"},
    )
    item = MemoryItem(
        id="memory-1",
        content="Rollback restored order processing",
        score=0.9,
        metadata={"kind": "operational_outcome"},
    )
    record = MemoryRecord(
        content=item.content,
        idempotency_key="incident-1:memory",
        scope=query.scope,
        metadata=item.metadata,
    )

    assert query.limit == 5
    assert item.score == 0.9
    assert record.scope == "sre/orders/prod"


@pytest.mark.parametrize(
    "model",
    [
        lambda: MemoryQuery(query="", limit=1),
        lambda: MemoryQuery(query="valid", limit=101),
        lambda: MemoryItem(id="memory", content="valid", score=1.1),
        lambda: MemoryRecord(content="valid", idempotency_key=""),
    ],
)
def test_memory_models_reject_invalid_bounds(model: object) -> None:
    with pytest.raises(ValidationError):
        model()  # type: ignore[operator]
