"""Versioned, public-safe replay dataset and rubric contracts."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FIXTURE_BYTES = 1_048_576
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "api_token",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "dsn",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
_SENSITIVE_VALUES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"[a-z][a-z0-9+.-]*://[^/@\s:]+:[^/@\s]+@", re.IGNORECASE),
)
_PROTECTED_LOCATOR = re.compile(
    r"^protected://[a-z0-9](?:[a-z0-9-]{0,62})/[a-z0-9](?:[a-z0-9._-]{0,127})$"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceState(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    STALE = "stale"
    MISMATCHED = "mismatched"


class ExpectedPolicy(StrEnum):
    RECOMMEND = "recommend"
    REVIEW = "review"
    SUPPRESS = "suppress"


class BaselineAction(StrEnum):
    NOTIFY = "notify"
    DISMISS = "dismiss"


class PublicProvenanceV1(StrictModel):
    schema_version: Literal["1"] = "1"
    origin: Literal["repository-authored-synthetic"]
    source_locator: str = Field(min_length=1, max_length=256)
    owner: str = Field(min_length=1, max_length=128)
    classification: Literal["C0-public-synthetic"]
    contains_real_data: Literal[False]
    redistribution_review: Literal["sample-approved"]
    reviewed_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class ReplayExpectationV1(StrictModel):
    actionable: bool
    expected_policy: ExpectedPolicy
    evidence_state: EvidenceState
    expected_evidence_ids: tuple[str, ...] = Field(default=(), max_length=16)
    baseline_action: BaselineAction
    baseline_handling_seconds: int = Field(ge=1, le=86_400)

    @model_validator(mode="after")
    def evidence_ids_match_state(self) -> Self:
        if self.evidence_state == EvidenceState.MISSING and self.expected_evidence_ids:
            raise ValueError("missing evidence cannot declare expected evidence IDs")
        if self.evidence_state != EvidenceState.MISSING and not self.expected_evidence_ids:
            raise ValueError("non-missing evidence requires expected evidence IDs")
        if not self.actionable and self.baseline_action == BaselineAction.NOTIFY:
            raise ValueError("the synthetic baseline cannot notify a non-actionable case")
        if len(self.expected_evidence_ids) != len(set(self.expected_evidence_ids)):
            raise ValueError("expected evidence IDs must be unique")
        if any(not item or len(item) > 128 for item in self.expected_evidence_ids):
            raise ValueError("expected evidence IDs must contain 1 to 128 characters")
        return self


class ReplayScenarioV1(StrictModel):
    scenario_id: str = Field(pattern=r"^SA-[0-9]{3}$")
    title: str = Field(min_length=1, max_length=256)
    service: Literal["front-end", "orders", "payment", "shipping"]
    severity: Literal["info", "warning", "error", "critical", "fatal"]
    count: int = Field(ge=1, le=10_000_000)
    users: int = Field(ge=0, le=10_000_000)
    environment: Literal["public-demo"] = "public-demo"
    expectation: ReplayExpectationV1
    tags: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def critical_cases_are_actionable(self) -> Self:
        if self.severity in {"critical", "fatal"} and not self.expectation.actionable:
            raise ValueError("critical synthetic cases must be actionable")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("scenario tags must be unique")
        if any(not item or len(item) > 64 for item in self.tags):
            raise ValueError("scenario tags must contain 1 to 64 characters")
        return self


class ReplayDatasetV1(StrictModel):
    schema_version: Literal["1"] = "1"
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    dataset_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    description: str = Field(min_length=1, max_length=1024)
    expected_case_count: int = Field(ge=1, le=1000)
    provenance: PublicProvenanceV1
    scenarios: tuple[ReplayScenarioV1, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_complete_scenarios(self) -> Self:
        if len(self.scenarios) != self.expected_case_count:
            raise ValueError("scenario count does not match expected_case_count")
        ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario IDs must be unique")
        return self


class ReplayThresholdsV1(StrictModel):
    actionable_precision_min: float = Field(ge=0, le=1)
    actionable_recall_min: float = Field(ge=0, le=1)
    critical_recall_min: float = Field(ge=0, le=1)
    severity_weighted_false_negative_max: float = Field(ge=0, le=1)
    evidence_validity_min: float = Field(ge=0, le=1)
    unsupported_claim_rate_max: float = Field(ge=0, le=1)
    reviewer_acceptance_min: float = Field(ge=0, le=1)
    unsafe_proposal_rate_max: float = Field(ge=0, le=1)
    median_handling_time_reduction_min: float = Field(ge=0, le=1)
    cost_per_completed_task_usd_max: float = Field(ge=0, le=1000)


class ReplayRubricV1(StrictModel):
    schema_version: Literal["1"] = "1"
    rubric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    rubric_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    decision_labels: tuple[Literal["recommend", "review", "suppress"], ...]
    critical_weight: int = Field(ge=1, le=100)
    high_weight: int = Field(ge=1, le=100)
    other_weight: int = Field(ge=1, le=100)
    thresholds: ReplayThresholdsV1
    provenance: PublicProvenanceV1

    @model_validator(mode="after")
    def decision_labels_are_complete(self) -> Self:
        if len(self.decision_labels) != 3 or set(self.decision_labels) != {
            "recommend",
            "review",
            "suppress",
        }:
            raise ValueError("rubric must define every decision label exactly once")
        return self


class ProtectedDatasetLocatorV1(StrictModel):
    """Non-secret handle; resolution and credentials stay outside this repository."""

    schema_version: Literal["1"] = "1"
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    dataset_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    locator: str = Field(min_length=1, max_length=256)
    owner: str = Field(min_length=1, max_length=128)
    classification: Literal["C1-protected-reference"]
    approval_reference: str = Field(min_length=1, max_length=256)
    digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def locator_uses_opaque_scheme(self) -> Self:
        if _PROTECTED_LOCATOR.fullmatch(self.locator) is None:
            raise ValueError("locator must use protected://<owner>/<dataset>")
        return self


def load_public_dataset(path: Path) -> ReplayDatasetV1:
    raw = _load_json(path)
    assert_public_fixture(raw)
    return ReplayDatasetV1.model_validate(raw)


def load_rubric(path: Path) -> ReplayRubricV1:
    raw = _load_json(path)
    assert_public_fixture(raw)
    return ReplayRubricV1.model_validate(raw)


def assert_public_fixture(value: Any, *, _depth: int = 0) -> None:
    """Reject obvious credential material before typed fixture validation."""

    if _depth > 32:
        raise ValueError("fixture nesting exceeds 32 levels")
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS:
                raise ValueError(f"sensitive field is forbidden in public fixtures: {key}")
            assert_public_fixture(item, _depth=_depth + 1)
    elif isinstance(value, list):
        for item in value:
            assert_public_fixture(item, _depth=_depth + 1)
    elif isinstance(value, str) and any(pattern.search(value) for pattern in _SENSITIVE_VALUES):
        raise ValueError("credential-like value is forbidden in public fixtures")


def _load_json(path: Path) -> Any:
    if path.stat().st_size > MAX_FIXTURE_BYTES:
        raise ValueError("fixture exceeds the one MiB limit")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_bytes(), object_pairs_hook=reject_duplicate_keys)
