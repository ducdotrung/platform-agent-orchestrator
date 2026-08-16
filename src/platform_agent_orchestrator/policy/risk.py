"""Deterministic action risk classification contracts."""

from __future__ import annotations

from typing import Protocol

from platform_agent_orchestrator.core.actions import ActionIntent, RiskLevel


class RiskClassifier(Protocol):
    """Resolve effective risk without relying on a workflow runtime."""

    def classify(self, action: ActionIntent) -> RiskLevel | None:
        """Return a classified risk or None when the action is unknown."""

        ...


class RequestedRiskClassifier:
    """Use the intent's explicit risk classification, preserving unknowns."""

    def classify(self, action: ActionIntent) -> RiskLevel | None:
        return action.requested_risk
