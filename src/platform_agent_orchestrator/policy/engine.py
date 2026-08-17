"""Policy engine extension contract."""

from __future__ import annotations

from typing import Protocol

from platform_agent_orchestrator.core.actions import ActionIntent
from platform_agent_orchestrator.core.approvals import ApprovalRequest
from platform_agent_orchestrator.core.context import ExecutionContext, ExecutionIdentity

from .models import PolicyDecision


class PolicyEngine(Protocol):
    """Evaluate an action before any supported mutation is invoked."""

    @property
    def version(self) -> str:
        """Return the immutable policy version used to bind approvals."""

        ...

    async def evaluate(
        self,
        action: ActionIntent,
        *,
        context: ExecutionContext,
    ) -> PolicyDecision:
        """Return allow, deny, or require-approval policy outcome."""

        ...

    def create_approval_request(
        self,
        action: ActionIntent,
        decision: PolicyDecision,
        *,
        identity: ExecutionIdentity,
        approval_id: str,
    ) -> ApprovalRequest:
        """Bind an approval request to this policy decision and identity."""

        ...
