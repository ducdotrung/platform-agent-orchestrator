from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.evaluation import (
    BaselineAction,
    EvidenceState,
    ProtectedDatasetLocatorV1,
    ReplayDatasetV1,
    assert_public_fixture,
    load_public_dataset,
    load_rubric,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "evaluation/datasets/sock-shop-alerts-v0.1.json"
RUBRIC_PATH = ROOT / "evaluation/rubrics/alert-intelligence-v1.json"


def test_fixed_public_dataset_matches_approved_baseline() -> None:
    dataset = load_public_dataset(DATASET_PATH)

    actionable = [item for item in dataset.scenarios if item.expectation.actionable]
    critical = [item for item in actionable if item.severity in {"critical", "fatal"}]
    notifications = [
        item
        for item in dataset.scenarios
        if item.expectation.baseline_action == BaselineAction.NOTIFY
    ]

    assert dataset.dataset_version == "0.1.0"
    assert len(dataset.scenarios) == 24
    assert len(actionable) == 10
    assert len(critical) == 4
    assert len(notifications) == 9
    assert {item.expectation.evidence_state for item in dataset.scenarios} == set(
        EvidenceState
    )
    assert any("prompt-injection" in item.tags for item in dataset.scenarios)
    assert dataset.provenance.contains_real_data is False


def test_dataset_rejects_missing_provenance_and_changed_counts() -> None:
    raw = json.loads(DATASET_PATH.read_text())
    raw.pop("provenance")
    with pytest.raises(ValidationError, match="provenance"):
        ReplayDatasetV1.model_validate(raw)

    raw = json.loads(DATASET_PATH.read_text())
    raw["expected_case_count"] = 23
    with pytest.raises(ValidationError, match="scenario count"):
        ReplayDatasetV1.model_validate(raw)


@pytest.mark.parametrize(
    "fixture",
    [
        {"api-token": "not-allowed"},
        {"nested": {"password": "not-allowed"}},
        {"value": "Bearer abcdefghijklmnopqrstuvwxyz"},
        {"value": "postgresql://sample:credential@database/sample"},
        {"value": "-----BEGIN PRIVATE KEY-----"},
    ],
)
def test_public_fixture_scan_rejects_credential_material(fixture: object) -> None:
    with pytest.raises(ValueError):
        assert_public_fixture(fixture)


def test_json_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"1","schema_version":"1"}')

    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_public_dataset(duplicate)


def test_rubric_materializes_approved_thresholds() -> None:
    rubric = load_rubric(RUBRIC_PATH)

    assert rubric.dataset_id == "sock-shop-alerts"
    assert rubric.thresholds.actionable_recall_min == 0.9
    assert rubric.thresholds.critical_recall_min == 1
    assert rubric.thresholds.evidence_validity_min == 1
    assert rubric.thresholds.unsupported_claim_rate_max == 0
    assert rubric.thresholds.cost_per_completed_task_usd_max == 0.02


def test_protected_dataset_locator_is_opaque_and_credential_free() -> None:
    values = {
        "dataset_id": "approved-alerts",
        "dataset_version": "1.2.0",
        "locator": "protected://evaluation/approved-alerts-v1",
        "owner": "Evaluation Owner",
        "classification": "C1-protected-reference",
        "approval_reference": "governance-review-123",
        "digest_sha256": "ab" * 32,
    }
    locator = ProtectedDatasetLocatorV1.model_validate(values)

    assert locator.locator == "protected://evaluation/approved-alerts-v1"
    for invalid in (
        "/private/data/alerts.json",
        "file:///private/data/alerts.json",
        "https://user:password@example.test/alerts.json",
    ):
        with pytest.raises(ValidationError, match="protected"):
            ProtectedDatasetLocatorV1.model_validate({**values, "locator": invalid})
