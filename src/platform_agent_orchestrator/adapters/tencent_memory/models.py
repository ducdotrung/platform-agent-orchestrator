"""TencentDB Agent Memory V3 wire and mapping models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class TencentAuthentication(BaseModel):
    """Authentication material owned only by the provider client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr = Field(repr=False)
    service_id: str = Field(min_length=1)

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "x-tdai-service-id": self.service_id,
        }


class TencentIsolation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    task_id: str | None = Field(default=None, min_length=1)


class TencentConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=8_192)
    timestamp: str | None = None


class TencentAddConversationRequest(TencentIsolation):
    messages: list[TencentConversationMessage] = Field(min_length=1, max_length=100)


class TencentSearchConversationRequest(TencentIsolation):
    query: str = Field(min_length=1, max_length=2_048)
    limit: int = Field(ge=1, le=100)
    time_start: str | None = None
    time_end: str | None = None


class TencentQueryConversationRequest(TencentIsolation):
    limit: int = Field(default=100, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class TencentConversationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1)
    timestamp: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    version: str | int | None = None


class TencentSearchConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    messages: list[TencentConversationItem]


class TencentQueryConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    messages: list[TencentConversationItem]
    total: int = Field(ge=0)


class TencentAddConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted_ids: list[str]
    accepted_versions: list[str | int] = Field(default_factory=list)
    total_count: int = Field(ge=0)


class TencentApiEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: int
    message: str
    request_id: str | None = None
    data: dict[str, Any]


class TencentStoredMemoryEnvelope(BaseModel):
    """Framework memory encoded inside a Tencent conversation message."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["platform.memory.v1"] = Field(alias="schema")
    content: str = Field(min_length=1)
    scope: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class TencentFeedbackEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_name: Literal["platform.memory.feedback.v1"] = Field(alias="schema")
    memory_id: str = Field(min_length=1)
    useful: bool
    reason: str | None = None
