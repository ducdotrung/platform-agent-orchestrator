"""Policy engine extension contract."""

from __future__ import annotations

from typing import Protocol

from platform_agent_orchestrator.core.actions import ActionIntent
from platform_agent_orchestrator.core.context import ExecutionContext

from .models import PolicyDecision


class PolicyEngine(Protocol):
    """Evaluate an action before any supported mutation is invoked."""

    async def evaluate(
        self,
        action: ActionIntent,
        *,
        context: ExecutionContext,
    ) -> PolicyDecision:
        """Return allow, deny, or require-approval policy outcome."""

        ...
