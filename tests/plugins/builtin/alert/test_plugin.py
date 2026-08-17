from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from platform_agent_orchestrator.contracts import (
    AlertReceivedPayloadV1,
    EventEnvelopeV1,
    EventType,
)
from platform_agent_orchestrator.core import (
    CapabilityRequest,
    CapabilityResult,
    DomainEvent,
    EvidenceRef,
    ExecutionContext,
)
from platform_agent_orchestrator.plugins.builtin.alert import AlertFlow, plugin
from platform_agent_orchestrator.registry import (
    AgentRegistry,
    CapabilityRegistry,
    FlowRegistry,
    validate_registry,
)
from platform_agent_orchestrator.runtime import RunMetadata, RunResult, RunStatus
from platform_agent_orchestrator.runtime.context import ExecutionContextFactory
from platform_agent_orchestrator.runtime.dispatcher import Dispatcher
from platform_agent_orchestrator.runtime.langgraph import LangGraphWorkflowRuntime
from platform_agent_orchestrator.sdk import CapabilityProvider, PluginContext

REQUIRED_CAPABILITIES = frozenset(
    {
        "alert.classify",
        "knowledge.search",
        "knowledge.change_impact",
        "notification.send",
    }
)
PLUGIN_ROOT = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "platform_agent_orchestrator"
    / "plugins"
    / "builtin"
    / "alert"
)


@dataclass
class RecordingAlertCapabilities:
    suppressed: bool = False
    confidence: float = 0.91
    include_recall: bool = True
    include_record: bool = True
    memory_worthy: bool = True
    requests: list[CapabilityRequest] = field(default_factory=list)
    notifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_records: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def capabilities(self) -> frozenset[str]:
        names = set(REQUIRED_CAPABILITIES)
        if self.include_recall:
            names.add("memory.recall")
        if self.include_record:
            names.add("memory.record")
        return frozenset(names)

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        del context
        self.requests.append(request)
        if request.capability == "alert.classify":
            classification = {
                "suppressed": self.suppressed,
                "classification": "known-noise" if self.suppressed else "actionable",
            }
            if self.suppressed:
                classification["suppression_reason"] = "Owned provider suppression"
            else:
                classification["priority"] = "P0"
            return CapabilityResult(
                success=True,
                data={"classification": classification},
            )
        if request.capability == "knowledge.search":
            evidence = EvidenceRef(
                kind="graph",
                locator="service://orders/payment",
                revision="graph-rev-1",
                label="Orders calls payment during checkout",
            )
            return CapabilityResult(
                success=True,
                data={"evidence": [evidence.model_dump(mode="json")]},
            )
        if request.capability == "memory.recall" and self.include_recall:
            return CapabilityResult(
                success=True,
                data={
                    "memories": [
                        {
                            "id": "alert-memory-1",
                            "content": "A previous timeout involved payment saturation",
                            "score": 0.88,
                            "metadata": {},
                        }
                    ]
                },
            )
        if request.capability == "knowledge.change_impact":
            return CapabilityResult(
                success=True,
                data={
                    "impact": {
                        "summary": "Checkout depends on the affected payment path",
                        "confidence": self.confidence,
                        "requires_review": self.confidence < 0.75,
                        "recommendation": "Inspect payment health before mitigation.",
                        "memory_worthy": self.memory_worthy,
                    }
                },
            )
        if request.capability == "notification.send":
            key = str(request.arguments["idempotency_key"])
            notification = dict(request.arguments)
            previous = self.notifications.setdefault(key, notification)
            if previous != notification:
                return CapabilityResult(success=False, error="notification conflict")
            return CapabilityResult(
                success=True,
                data={"receipt": f"notification:{key}"},
            )
        if request.capability == "memory.record" and self.include_record:
            key = str(request.arguments["idempotency_key"])
            self.memory_records.setdefault(key, dict(request.arguments))
            return CapabilityResult(success=True, data={"receipt": f"memory:{key}"})
        return CapabilityResult(success=False, error="unsupported test capability")


class Policies:
    def register(self, name: str, policy: object) -> None:
        del name, policy


def alert_event(
    *,
    event_id: str = "alert-event-1",
    event_type: str = "monitoring.alert.received",
    title: str = "Payment timeout",
) -> DomainEvent:
    return DomainEvent(
        id=event_id,
        type=event_type,
        source="sre-alert-tests",
        subject="PAYMENT-1",
        occurred_at=datetime(2026, 8, 17, tzinfo=UTC),
        correlation_id=f"correlation-{event_id}",
        idempotency_key=f"sre-alert:{event_id}",
        tenant_id="tenant-1",
        data={
            "alert_id": "PAYMENT-1",
            "title": title,
            "service": "order-service",
            "severity": "critical",
            "environment": "prod",
            "count": 200,
            "users": 25,
        },
    )


def build_dispatcher(
    provider: CapabilityProvider,
) -> tuple[Dispatcher, CapabilityRegistry, AgentRegistry, FlowRegistry]:
    capabilities = CapabilityRegistry()
    capabilities.register(provider)
    agents = AgentRegistry()
    flows = FlowRegistry()
    plugin.register(
        PluginContext(
            flows=flows,
            agents=agents,
            capabilities=capabilities,
            policies=Policies(),
        )
    )
    validate_registry(flows=flows, capabilities=capabilities)
    dispatcher = Dispatcher(
        flows=flows,
        runtime=LangGraphWorkflowRuntime(),
        contexts=ExecutionContextFactory(
            capabilities=capabilities,
            agents=agents,
            policy=object(),
            observability=object(),
        ),
    )
    return dispatcher, capabilities, agents, flows


def dispatch(
    provider: RecordingAlertCapabilities,
    event: DomainEvent | None = None,
) -> RunResult:
    dispatcher, _capabilities, _agents, _flows = build_dispatcher(provider)
    results = asyncio.run(dispatcher.dispatch(event or alert_event()))
    assert len(results) == 1
    return results[0]


def test_classification_can_suppress_without_orchestrator_policy() -> None:
    provider = RecordingAlertCapabilities(suppressed=True)

    result = dispatch(provider, alert_event(title="Provider-owned noise"))

    assert result.status is RunStatus.SUCCEEDED
    assert result.output["status"] == "suppressed"
    assert result.output["classification"]["suppression_reason"] == (
        "Owned provider suppression"
    )
    assert [request.capability for request in provider.requests] == ["alert.classify"]
    assert not provider.notifications


def test_knowledge_and_memory_are_supplied_to_impact_assessment() -> None:
    provider = RecordingAlertCapabilities(memory_worthy=False)

    result = dispatch(provider)

    assert result.status is RunStatus.SUCCEEDED
    impact_request = next(
        request
        for request in provider.requests
        if request.capability == "knowledge.change_impact"
    )
    assert impact_request.arguments["evidence"][0]["locator"] == (
        "service://orders/payment"
    )
    assert impact_request.arguments["memories"][0]["id"] == "alert-memory-1"
    assert result.output["status"] == "notified"


def test_missing_optional_memory_does_not_block_alert() -> None:
    provider = RecordingAlertCapabilities(include_recall=False, include_record=False)

    result = dispatch(provider)

    assert result.status is RunStatus.SUCCEEDED
    assert result.output["memory_available"] is False
    assert result.output["memory_recorded"] is False
    assert not any(
        request.capability.startswith("memory.") for request in provider.requests
    )


def test_low_confidence_pauses_and_resumes_through_framework_contract() -> None:
    provider = RecordingAlertCapabilities(confidence=0.4, memory_worthy=False)
    dispatcher, _capabilities, _agents, flows = build_dispatcher(provider)
    event = alert_event()

    paused = asyncio.run(dispatcher.dispatch(event))[0]

    assert paused.status is RunStatus.PAUSED
    assert paused.pause is not None
    assert paused.pause.approval is None
    assert paused.pause.payload["kind"] == "alert_review"
    assert paused.output["review_status"] == "pending"
    assert not provider.notifications

    run = RunMetadata(
        run_id=paused.run_id,
        flow_name="alert",
        flow_version=flows.get("alert").metadata.version,
        thread_id=paused.run_id,
        correlation_id=event.correlation_id,
        tenant_id=event.tenant_id,
        status=RunStatus.PAUSED.value,
    )
    resumed = asyncio.run(
        dispatcher.resume(
            run,
            {"approved": True, "actor": "on-call", "reason": "Evidence reviewed"},
        )
    )

    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.output["review"]["approved"] is True
    assert resumed.output["status"] == "notified"
    assert len(provider.notifications) == 1


def test_notification_is_idempotent_for_replayed_event() -> None:
    provider = RecordingAlertCapabilities(memory_worthy=False)
    dispatcher, _capabilities, _agents, _flows = build_dispatcher(provider)
    event = alert_event()

    first = asyncio.run(dispatcher.dispatch(event))[0]
    second = asyncio.run(dispatcher.dispatch(event))[0]

    assert first.output["notification_receipt"] == second.output["notification_receipt"]
    assert len(provider.notifications) == 1
    assert set(provider.notifications) == {"sre-alert:alert-event-1:recommendation"}


def test_memory_write_is_selective_and_idempotent() -> None:
    provider = RecordingAlertCapabilities(memory_worthy=False)

    trivial = dispatch(provider, alert_event(event_id="alert-trivial"))
    assert trivial.output["memory_recorded"] is False
    assert not provider.memory_records

    provider.memory_worthy = True
    important = dispatch(provider, alert_event(event_id="alert-important"))
    repeated = dispatch(provider, alert_event(event_id="alert-important"))

    assert important.output["memory_recorded"] is True
    assert repeated.output["memory_recorded"] is True
    assert len(provider.memory_records) == 1
    assert set(provider.memory_records) == {"sre-alert:alert-important:memory"}


def test_plugin_registration_and_dependency_boundary() -> None:
    provider = RecordingAlertCapabilities()
    _dispatcher, capabilities, agents, flows = build_dispatcher(provider)

    assert dict(agents.list()) == {}
    flow = flows.get("alert")
    assert isinstance(flow, AlertFlow)
    assert flow.metadata.event_types == frozenset({"monitoring.alert.received"})
    assert flow.metadata.required_capabilities == REQUIRED_CAPABILITIES
    assert flow.metadata.optional_capabilities == frozenset(
        {"memory.recall", "memory.record"}
    )
    validate_registry(flows=flows, capabilities=capabilities)

    forbidden: list[str] = []
    forbidden_prefixes = (
        "langchain",
        "langgraph",
        "gitnexus",
        "deepwiki",
        "tencent",
        "platform_agent_orchestrator.adapters",
    )
    for path in PLUGIN_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if module.lower().startswith(forbidden_prefixes):
                    forbidden.append(f"{path.name}:{node.lineno}:{module}")
    assert forbidden == []


def test_event_migration_is_explicit_and_rejects_legacy_type() -> None:
    flow = AlertFlow()

    assert flow.accepts(alert_event())
    assert not flow.accepts(alert_event(event_type="alert.received"))
    assert EventType.ALERT_RECEIVED.value == "monitoring.alert.received"

    payload = AlertReceivedPayloadV1(
        alert_id="PAYMENT-1",
        title="Payment timeout",
        service="order-service",
        severity="critical",
        environment="prod",
        count=200,
        users=25,
    )
    envelope = EventEnvelopeV1(
        type="monitoring.alert.received",
        source="sre-alert-tests",
        subject="PAYMENT-1",
        idempotency_key="sre-alert:envelope-1",
        payload=payload,
    )
    assert envelope.type == "monitoring.alert.received"
    with pytest.raises(ValidationError):
        EventEnvelopeV1.model_validate(
            {**envelope.model_dump(mode="json"), "type": "alert.received"}
        )
