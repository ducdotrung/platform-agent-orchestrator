"""Versioned durable-service contracts with bounded public serialization."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import utc_now

PUBLIC_REDACTION = "[REDACTED]"
_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "set_cookie",
    "signature",
    "token",
}
_SENSITIVE_SUFFIXES = (
    "_api_key",
    "_authorization",
    "_cookie",
    "_credential",
    "_password",
    "_secret",
    "_signature",
    "_token",
)


def _redact_public(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES):
                result[str(key)] = PUBLIC_REDACTION
            else:
                result[str(key)] = _redact_public(item)
        return result
    if isinstance(value, list):
        return [_redact_public(item) for item in value]
    return value


class PublicContract(BaseModel):
    """Strict-shape contract with an intentional public-output boundary."""

    model_config = ConfigDict(extra="forbid")
    public_exclude: ClassVar[frozenset[str]] = frozenset()

    def public_dump(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude=self.public_exclude)
        return _redact_public(data)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED_TERMINAL = "failed_terminal"
    DEAD_LETTERED = "dead_lettered"
    QUARANTINED = "quarantined"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED_TERMINAL = "failed_terminal"
    DEAD_LETTERED = "dead_lettered"
    QUARANTINED = "quarantined"


class DeliveryKind(StrEnum):
    INVOKE = "invoke"
    RESUME = "resume"


class RetryCategory(StrEnum):
    RETRYABLE_TRANSIENT = "retryable_transient"
    WORKER_LOST = "worker_lost"
    TERMINAL_INPUT = "terminal_input"
    TERMINAL_DEPENDENCY = "terminal_dependency"
    TERMINAL_POLICY = "terminal_policy"
    AMBIGUOUS_SIDE_EFFECT = "ambiguous_side_effect"
    POISON_OR_SECURITY = "poison_or_security"


class RetryDisposition(StrEnum):
    RETRY = "retry"
    RECONCILE = "reconcile"
    FAIL = "fail"
    QUARANTINE = "quarantine"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ActorType(StrEnum):
    SERVICE = "service"
    REVIEWER = "reviewer"
    OPERATOR = "operator"


class FeedbackRating(StrEnum):
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    UNSAFE = "unsafe"


class ErrorContractV1(PublicContract):
    schema_version: Literal["1"] = "1"
    code: str = Field(min_length=1, max_length=128)
    category: RetryCategory
    summary: str = Field(min_length=1, max_length=2_048)
    fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_retryable_category(self) -> Self:
        retryable_categories = {
            RetryCategory.RETRYABLE_TRANSIENT,
            RetryCategory.WORKER_LOST,
        }
        if self.retryable != (self.category in retryable_categories):
            raise ValueError("retryable must agree with deterministic error category policy")
        return self


class RetryContractV1(PublicContract):
    schema_version: Literal["1"] = "1"
    category: RetryCategory
    disposition: RetryDisposition
    attempt: int = Field(ge=1, le=100)
    retry_at: datetime | None = None
    error: ErrorContractV1

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        allowed = {
            RetryCategory.RETRYABLE_TRANSIENT: {RetryDisposition.RETRY},
            RetryCategory.WORKER_LOST: {RetryDisposition.RETRY},
            RetryCategory.TERMINAL_INPUT: {RetryDisposition.FAIL},
            RetryCategory.TERMINAL_DEPENDENCY: {RetryDisposition.FAIL},
            RetryCategory.TERMINAL_POLICY: {
                RetryDisposition.FAIL,
                RetryDisposition.QUARANTINE,
            },
            RetryCategory.AMBIGUOUS_SIDE_EFFECT: {RetryDisposition.RECONCILE},
            RetryCategory.POISON_OR_SECURITY: {RetryDisposition.QUARANTINE},
        }
        if self.disposition not in allowed[self.category]:
            raise ValueError("disposition is incompatible with deterministic retry category")
        if (self.disposition == RetryDisposition.RETRY) != (self.retry_at is not None):
            raise ValueError("retry_at must be present exactly for retry disposition")
        if self.error.category != self.category:
            raise ValueError("retry and error categories must match")
        return self


class DeliveryContractV1(PublicContract):
    schema_version: Literal["1"] = "1"
    job_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    kind: DeliveryKind
    operation_key: str = Field(min_length=1, max_length=256)
    status: DeliveryStatus
    available_at: datetime
    attempt_count: int = Field(ge=0, le=100)
    max_attempts: int = Field(default=5, ge=1, le=100)
    lease_owner: str | None = Field(default=None, max_length=128)
    lease_token: str | None = Field(default=None, max_length=256, repr=False)
    lease_expires_at: datetime | None = None
    error: ErrorContractV1 | None = None
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_lease(self) -> Self:
        lease = (self.lease_owner, self.lease_token, self.lease_expires_at)
        if self.status == DeliveryStatus.LEASED and any(item is None for item in lease):
            raise ValueError("leased delivery requires owner, token, and expiry")
        if self.status != DeliveryStatus.LEASED and any(item is not None for item in lease):
            raise ValueError("lease fields are only valid for leased delivery")
        if self.attempt_count > self.max_attempts:
            raise ValueError("attempt_count cannot exceed max_attempts")
        return self


class RunContractV1(PublicContract):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    scope_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    workflow: Literal["alert"] = "alert"
    workflow_contract_version: Literal["1"] = "1"
    status: RunStatus
    result_summary: str | None = Field(default=None, max_length=16_384)
    error: ErrorContractV1 | None = None
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    interrupted_at: datetime | None = None
    finished_at: datetime | None = None
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_state_timestamps(self) -> Self:
        terminal = {
            RunStatus.SUCCEEDED,
            RunStatus.REJECTED,
            RunStatus.FAILED_TERMINAL,
            RunStatus.DEAD_LETTERED,
            RunStatus.QUARANTINED,
        }
        if (self.status in terminal) != (self.finished_at is not None):
            raise ValueError("finished_at must be present exactly for terminal run states")
        if self.status == RunStatus.WAITING_APPROVAL and self.interrupted_at is None:
            raise ValueError("waiting_approval requires interrupted_at")
        if self.thread_id != self.run_id:
            raise ValueError("thread_id must equal run_id")
        return self


class ApprovalContractV1(PublicContract):
    schema_version: Literal["1"] = "1"
    approval_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    approval_version: int = Field(ge=1)
    decision: ApprovalDecision
    actor_id: str = Field(min_length=1, max_length=256)
    actor_type: Literal[ActorType.REVIEWER, ActorType.OPERATOR]
    reason: str = Field(min_length=1, max_length=2_048)
    action_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    policy_version: str = Field(min_length=1, max_length=128)
    decided_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime

    @model_validator(mode="after")
    def reject_expired_decision(self) -> Self:
        if self.decided_at > self.expires_at:
            raise ValueError("approval cannot be decided after expiry")
        return self


class FeedbackContractV1(PublicContract):
    schema_version: Literal["1"] = "1"
    feedback_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(min_length=1, max_length=256)
    rating: FeedbackRating
    reason: str = Field(min_length=1, max_length=2_048)
    trace_id: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
