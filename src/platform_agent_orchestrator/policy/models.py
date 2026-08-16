"""Runtime-neutral policy decisions and configuration."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from platform_agent_orchestrator.core.actions import RiskLevel

PolicyOutcome: TypeAlias = Literal["allow", "deny", "require_approval"]


class PolicyDecision(BaseModel):
    """Deterministic decision returned before any action provider invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: PolicyOutcome
    reason: str = Field(min_length=1)
    effective_risk: RiskLevel


class DefaultPolicyConfig(BaseModel):
    """Configuration for conservative default mutation policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(default="default-v1", min_length=1, max_length=128)
    denied_capabilities: frozenset[str] = Field(default_factory=frozenset)
    safe_capabilities: frozenset[str] = Field(default_factory=frozenset)
    safe_resources: dict[str, frozenset[str]] = Field(default_factory=dict)
    caution_outcome: PolicyOutcome = "require_approval"
    unknown_mutation_outcome: Literal["deny", "require_approval"] = "deny"
