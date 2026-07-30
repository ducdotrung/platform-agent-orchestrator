from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.service_contracts import (
    PUBLIC_REDACTION,
    ActorType,
    ApprovalContractV1,
    ApprovalDecision,
    DeliveryContractV1,
    DeliveryKind,
    DeliveryStatus,
    ErrorContractV1,
    FeedbackContractV1,
    FeedbackRating,
    RetryCategory,
    RetryContractV1,
    RetryDisposition,
    RunContractV1,
    RunStatus,
)

NOW = datetime(2026, 7, 30, tzinfo=UTC)
FINGERPRINT = "a" * 64


def error(category: RetryCategory = RetryCategory.RETRYABLE_TRANSIENT) -> ErrorContractV1:
    return ErrorContractV1(
        code="dependency_timeout",
        category=category,
        summary="Sample dependency timed out",
        fingerprint=FINGERPRINT,
        retryable=category in {
            RetryCategory.RETRYABLE_TRANSIENT,
            RetryCategory.WORKER_LOST,
        },
    )


def test_state_enums_are_compatible_with_adrs() -> None:
    assert {item.value for item in RunStatus} == {
        "queued",
        "running",
        "waiting_approval",
        "retry_wait",
        "succeeded",
        "rejected",
        "failed_terminal",
        "dead_lettered",
        "quarantined",
    }
    assert {item.value for item in DeliveryStatus} == {
        "pending",
        "leased",
        "retry_wait",
        "completed",
        "failed_terminal",
        "dead_lettered",
        "quarantined",
    }
    assert {item.value for item in RetryCategory} == {
        "retryable_transient",
        "worker_lost",
        "terminal_input",
        "terminal_dependency",
        "terminal_policy",
        "ambiguous_side_effect",
        "poison_or_security",
    }
    assert {item.value for item in RetryDisposition} == {
        "retry",
        "reconcile",
        "fail",
        "quarantine",
    }
    assert {item.value for item in ApprovalDecision} == {"approved", "rejected"}
    assert {item.value for item in FeedbackRating} == {
        "helpful",
        "not_helpful",
        "unsafe",
    }


@pytest.mark.parametrize("status", list(RunStatus))
def test_every_run_state_serializes_publicly(status: RunStatus) -> None:
    terminal = status in {
        RunStatus.SUCCEEDED,
        RunStatus.REJECTED,
        RunStatus.FAILED_TERMINAL,
        RunStatus.DEAD_LETTERED,
        RunStatus.QUARANTINED,
    }
    contract = RunContractV1(
        run_id="run-1",
        event_id="event-1",
        scope_id="sample",
        thread_id="run-1",
        status=status,
        interrupted_at=NOW if status == RunStatus.WAITING_APPROVAL else None,
        finished_at=NOW if terminal else None,
    )

    assert contract.public_dump()["status"] == status.value


@pytest.mark.parametrize("status", list(DeliveryStatus))
def test_every_delivery_state_serializes_publicly(status: DeliveryStatus) -> None:
    leased = status == DeliveryStatus.LEASED
    contract = DeliveryContractV1(
        job_id="job-1",
        run_id="run-1",
        kind=DeliveryKind.INVOKE,
        operation_key="invoke-1",
        status=status,
        available_at=NOW,
        attempt_count=1,
        lease_owner="worker-1" if leased else None,
        lease_token="capability-secret" if leased else None,
        lease_expires_at=NOW + timedelta(seconds=30) if leased else None,
    )

    public = contract.public_dump()
    assert public["status"] == status.value
    if leased:
        assert public["lease_token"] == PUBLIC_REDACTION


@pytest.mark.parametrize(
    ("category", "disposition"),
    [
        (RetryCategory.RETRYABLE_TRANSIENT, RetryDisposition.RETRY),
        (RetryCategory.WORKER_LOST, RetryDisposition.RETRY),
        (RetryCategory.TERMINAL_INPUT, RetryDisposition.FAIL),
        (RetryCategory.TERMINAL_DEPENDENCY, RetryDisposition.FAIL),
        (RetryCategory.TERMINAL_POLICY, RetryDisposition.QUARANTINE),
        (RetryCategory.AMBIGUOUS_SIDE_EFFECT, RetryDisposition.RECONCILE),
        (RetryCategory.POISON_OR_SECURITY, RetryDisposition.QUARANTINE),
    ],
)
def test_every_retry_category_has_a_compatible_disposition(
    category: RetryCategory, disposition: RetryDisposition
) -> None:
    contract = RetryContractV1(
        category=category,
        disposition=disposition,
        attempt=2,
        retry_at=NOW + timedelta(seconds=2) if disposition == RetryDisposition.RETRY else None,
        error=error(category),
    )
    assert contract.public_dump()["disposition"] == disposition.value


def test_retry_contract_rejects_incompatible_category() -> None:
    with pytest.raises(ValidationError):
        RetryContractV1(
            category=RetryCategory.TERMINAL_INPUT,
            disposition=RetryDisposition.RETRY,
            attempt=1,
            retry_at=NOW,
            error=error(RetryCategory.TERMINAL_INPUT),
        )


def test_approval_contract_rejects_expired_and_service_actor_decisions() -> None:
    values = {
        "approval_id": "approval-1",
        "run_id": "run-1",
        "approval_version": 1,
        "decision": ApprovalDecision.APPROVED,
        "actor_id": "reviewer-1",
        "actor_type": ActorType.REVIEWER,
        "reason": "Reviewed sample evidence",
        "action_hash": FINGERPRINT,
        "policy_version": "sample-v1",
        "decided_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    assert ApprovalContractV1(**values).public_dump()["decision"] == "approved"

    with pytest.raises(ValidationError):
        ApprovalContractV1(**(values | {"actor_type": ActorType.SERVICE}))
    with pytest.raises(ValidationError):
        ApprovalContractV1(**(values | {"expires_at": NOW - timedelta(seconds=1)}))


def test_feedback_and_error_public_serialization_redacts_nested_secrets() -> None:
    feedback = FeedbackContractV1(
        feedback_id="feedback-1",
        run_id="run-1",
        actor_id="reviewer-1",
        rating=FeedbackRating.HELPFUL,
        reason="Evidence was relevant",
        metadata={
            "authorization": "Bearer secret",
            "password": "secret",
            "client_api_key": "secret",
            "nested": [{"provider_token": "secret"}],
            "safe": "sample",
        },
    )

    public = feedback.public_dump()

    assert public["metadata"]["authorization"] == PUBLIC_REDACTION
    assert public["metadata"]["password"] == PUBLIC_REDACTION
    assert public["metadata"]["client_api_key"] == PUBLIC_REDACTION
    assert public["metadata"]["nested"][0]["provider_token"] == PUBLIC_REDACTION
    assert public["metadata"]["safe"] == "sample"

    public_error = error().model_copy(
        update={"details": {"proxy-authorization": "secret", "safe_code": 503}}
    ).public_dump()
    assert public_error["details"]["proxy-authorization"] == PUBLIC_REDACTION
    assert public_error["details"]["safe_code"] == 503


@pytest.mark.parametrize(
    "contract",
    [
        error(),
        RetryContractV1(
            category=RetryCategory.RETRYABLE_TRANSIENT,
            disposition=RetryDisposition.RETRY,
            attempt=1,
            retry_at=NOW,
            error=error(),
        ),
        DeliveryContractV1(
            job_id="job-1",
            run_id="run-1",
            kind=DeliveryKind.INVOKE,
            operation_key="invoke-1",
            status=DeliveryStatus.PENDING,
            available_at=NOW,
            attempt_count=0,
        ),
        RunContractV1(
            run_id="run-1",
            event_id="event-1",
            scope_id="sample",
            thread_id="run-1",
            status=RunStatus.QUEUED,
        ),
        ApprovalContractV1(
            approval_id="approval-1",
            run_id="run-1",
            approval_version=1,
            decision=ApprovalDecision.REJECTED,
            actor_id="reviewer-1",
            actor_type=ActorType.REVIEWER,
            reason="Needs more evidence",
            action_hash=FINGERPRINT,
            policy_version="sample-v1",
            decided_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
        FeedbackContractV1(
            feedback_id="feedback-1",
            run_id="run-1",
            actor_id="reviewer-1",
            rating=FeedbackRating.NOT_HELPFUL,
            reason="Missing dependency evidence",
        ),
    ],
)
def test_every_service_contract_has_versioned_forbid_extra_schema(contract: object) -> None:
    assert contract.public_dump()["schema_version"] == "1"  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        type(contract).model_validate(contract.model_dump() | {"unknown": True})  # type: ignore[attr-defined]
