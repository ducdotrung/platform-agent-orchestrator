"""Cross-boundary memory item model used by agent requests.

The complete provider-neutral MemoryPort is introduced in Task 13.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MemoryItem(BaseModel):
    """A bounded memory recalled from any configured memory provider."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
