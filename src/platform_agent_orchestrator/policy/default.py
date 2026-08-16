"""Conservative default policy implementation."""

from __future__ import annotations

from platform_agent_orchestrator.core.actions import ActionIntent, RiskLevel
from platform_agent_orchestrator.core.approvals import ApprovalRequest
from platform_agent_orchestrator.core.context import ExecutionContext, ExecutionIdentity

from .models import DefaultPolicyConfig, PolicyDecision
from .risk import RequestedRiskClassifier, RiskClassifier


class DefaultPolicyEngine:
    """Apply deterministic deny, allow-list, and approval rules."""

    def __init__(
        self,
        config: DefaultPolicyConfig | None = None,
        *,
        risk_classifier: RiskClassifier | None = None,
    ) -> None:
        self.config = config or DefaultPolicyConfig()
        self._risk_classifier = risk_classifier or RequestedRiskClassifier()

    async def evaluate(
        self,
        action: ActionIntent,
        *,
        context: ExecutionContext,
    ) -> PolicyDecision:
        """Evaluate an action without invoking providers or causing side effects."""

        del context
        classified = self._risk_classifier.classify(action)
        effective_risk = classified or RiskLevel.RISKY

        if action.capability in self.config.denied_capabilities:
            return PolicyDecision(
                outcome="deny",
                reason=f"capability {action.capability!r} is explicitly denied",
                effective_risk=effective_risk,
            )

        if classified is None:
            return PolicyDecision(
                outcome=self.config.unknown_mutation_outcome,
                reason="action risk is unclassified; conservative policy applies",
                effective_risk=RiskLevel.RISKY,
            )

        if classified == RiskLevel.READ_ONLY:
            return PolicyDecision(
                outcome="allow",
                reason="read-only action is allowed",
                effective_risk=classified,
            )

        if classified == RiskLevel.SAFE:
            if self._is_safe_allowlisted(action):
                return PolicyDecision(
                    outcome="allow",
                    reason="safe action matches the configured allow-list",
                    effective_risk=classified,
                )
            return PolicyDecision(
                outcome="deny",
                reason="safe mutation is not present in the configured allow-list",
                effective_risk=classified,
            )

        if classified == RiskLevel.CAUTION:
            outcome = self.config.caution_outcome
            if outcome == "allow" and not self._is_safe_allowlisted(action):
                outcome = "deny"
            return PolicyDecision(
                outcome=outcome,
                reason=(
                    "caution action follows configured policy"
                    if outcome != "deny"
                    else "caution action is not approved by configured policy"
                ),
                effective_risk=classified,
            )

        return PolicyDecision(
            outcome="require_approval",
            reason="risky action requires explicit human approval",
            effective_risk=RiskLevel.RISKY,
        )

    def create_approval_request(
        self,
        action: ActionIntent,
        decision: PolicyDecision,
        *,
        identity: ExecutionIdentity,
        approval_id: str,
    ) -> ApprovalRequest:
        """Bind an approval request to a require-approval decision."""

        if decision.outcome != "require_approval":
            raise ValueError("approval requests require a require_approval policy decision")
        return ApprovalRequest.for_action(
            action,
            identity=identity,
            approval_id=approval_id,
            policy_version=self.config.version,
            reason=decision.reason,
        )

    def _is_safe_allowlisted(self, action: ActionIntent) -> bool:
        if action.capability not in self.config.safe_capabilities:
            return False
        resources = self.config.safe_resources.get(action.capability)
        return resources is None or action.resource in resources
