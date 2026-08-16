from __future__ import annotations

import asyncio

from platform_agent_orchestrator.core import RiskLevel, compute_action_hash
from platform_agent_orchestrator.policy import DefaultPolicyConfig, DefaultPolicyEngine

from .helpers import action, context, identity


def evaluate(engine: DefaultPolicyEngine, risk: RiskLevel | None):
    return asyncio.run(engine.evaluate(action(risk), context=context()))


def test_read_only_action_is_allowed_by_default() -> None:
    decision = evaluate(DefaultPolicyEngine(), RiskLevel.READ_ONLY)

    assert decision.outcome == "allow"
    assert decision.effective_risk == RiskLevel.READ_ONLY


def test_risky_action_requires_explicit_approval() -> None:
    decision = evaluate(DefaultPolicyEngine(), RiskLevel.RISKY)

    assert decision.outcome == "require_approval"
    assert decision.effective_risk == RiskLevel.RISKY


def test_policy_engine_creates_request_bound_to_required_action() -> None:
    engine = DefaultPolicyEngine()
    intent = action(RiskLevel.RISKY)
    decision = asyncio.run(engine.evaluate(intent, context=context()))

    request = engine.create_approval_request(
        intent,
        decision,
        identity=identity(),
        approval_id="approval-1",
    )

    assert request.action_hash == compute_action_hash(intent)
    assert request.policy_version == "default-v1"
    assert request.run_id == "run-1"


def test_unknown_mutation_is_not_silently_allowed() -> None:
    decision = evaluate(DefaultPolicyEngine(), None)

    assert decision.outcome == "deny"
    assert decision.effective_risk == RiskLevel.RISKY


def test_safe_mutation_requires_capability_and_resource_allow_list() -> None:
    engine = DefaultPolicyEngine(
        DefaultPolicyConfig(
            safe_capabilities=frozenset({"infra.execute"}),
            safe_resources={"infra.execute": frozenset({"service/orders"})},
        )
    )

    assert evaluate(engine, RiskLevel.SAFE).outcome == "allow"


def test_unlisted_safe_mutation_is_denied() -> None:
    assert evaluate(DefaultPolicyEngine(), RiskLevel.SAFE).outcome == "deny"


def test_caution_action_requires_approval_by_default() -> None:
    assert evaluate(DefaultPolicyEngine(), RiskLevel.CAUTION).outcome == "require_approval"


def test_explicit_denial_overrides_read_only_allow() -> None:
    engine = DefaultPolicyEngine(
        DefaultPolicyConfig(denied_capabilities=frozenset({"infra.execute"}))
    )

    assert evaluate(engine, RiskLevel.READ_ONLY).outcome == "deny"
