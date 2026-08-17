from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from platform_agent_orchestrator.core import (
    ActionIntent,
    ActionResult,
    ApprovalActionMismatchError,
    CapabilityRequest,
    CapabilityResult,
    DomainEvent,
    ExecutionContext,
    ExecutionIdentity,
)
from platform_agent_orchestrator.plugins.builtin.sre import SREFlow, plugin
from platform_agent_orchestrator.plugins.builtin.sre.flow import _approval
from platform_agent_orchestrator.policy import DefaultPolicyEngine
from platform_agent_orchestrator.registry import AgentRegistry, CapabilityRegistry, FlowRegistry
from platform_agent_orchestrator.runtime import RunMetadata, RunResult, RunStatus
from platform_agent_orchestrator.runtime.context import ExecutionContextFactory
from platform_agent_orchestrator.runtime.dispatcher import Dispatcher
from platform_agent_orchestrator.runtime.langgraph import LangGraphWorkflowRuntime
from platform_agent_orchestrator.sdk import CapabilityProvider, NodeContext, PluginContext

REQUIRED_CAPABILITIES = frozenset({"infra.execute", "infra.verify"})
PLUGIN_ROOT = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "platform_agent_orchestrator"
    / "plugins"
    / "builtin"
    / "sre"
)


@dataclass
class RecordingSRECapabilities:
    include_knowledge: bool = True
    include_recall: bool = True
    include_record: bool = True
    include_notification: bool = True
    execution_failure: bool = False
    verification_failure: bool = False
    timeline: list[str] = field(default_factory=list)
    requests: list[CapabilityRequest] = field(default_factory=list)
    mutations: dict[str, dict[str, Any]] = field(default_factory=dict)
    notifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_records: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def capabilities(self) -> frozenset[str]:
        names = set(REQUIRED_CAPABILITIES)
        if self.include_knowledge:
            names.add("knowledge.search")
        if self.include_recall:
            names.add("memory.recall")
        if self.include_record:
            names.add("memory.record")
        if self.include_notification:
            names.add("notification.send")
        return frozenset(names)

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        del context
        self.requests.append(request)
        self.timeline.append(request.capability)
        if request.capability == "knowledge.search":
            return CapabilityResult(
                success=True,
                data={"evidence": [{"kind": "docs", "locator": "runbook://orders"}]},
            )
        if request.capability == "memory.recall":
            return CapabilityResult(
                success=True,
                data={"memories": [{"id": "prior-1", "content": "Restart was safe"}]},
            )
        if request.capability == "infra.execute":
            action = ActionIntent.model_validate(request.arguments["action"])
            previous = self.mutations.setdefault(
                action.idempotency_key,
                {
                    "action_hash": request.arguments["action_hash"],
                    "action": action.model_dump(mode="json"),
                },
            )
            if previous["action_hash"] != request.arguments["action_hash"]:
                return CapabilityResult(success=False, error="idempotency conflict")
            result = ActionResult(
                success=not self.execution_failure,
                status="execution_failed" if self.execution_failure else "completed",
                output={"provider_receipt": "infra-1"},
                receipt_id="infra-1",
                error="provider rejected mutation" if self.execution_failure else None,
            )
            return CapabilityResult(
                success=True,
                data={"result": result.model_dump(mode="json")},
            )
        if request.capability == "infra.verify":
            return CapabilityResult(
                success=True,
                data={
                    "verified": not self.verification_failure,
                    "reason": "health check failed" if self.verification_failure else "healthy",
                },
            )
        if request.capability == "notification.send":
            key = str(request.arguments["idempotency_key"])
            previous = self.notifications.setdefault(key, dict(request.arguments))
            if previous != request.arguments:
                return CapabilityResult(success=False, error="notification conflict")
            return CapabilityResult(success=True, data={"receipt": f"notification:{key}"})
        if request.capability == "memory.record":
            key = str(request.arguments["idempotency_key"])
            self.memory_records.setdefault(key, dict(request.arguments))
            return CapabilityResult(success=True, data={"receipt": f"memory:{key}"})
        return CapabilityResult(success=False, error="unsupported test capability")


class TrackingPolicy(DefaultPolicyEngine):
    def __init__(self, timeline: list[str]) -> None:
        super().__init__()
        self.timeline = timeline
        self.evaluated: list[ActionIntent] = []

    async def evaluate(
        self,
        action: ActionIntent,
        *,
        context: ExecutionContext,
    ):
        self.timeline.append("policy.evaluate")
        self.evaluated.append(action)
        return await super().evaluate(action, context=context)


class Policies:
    def register(self, name: str, policy: object) -> None:
        del name, policy


def sre_event(
    *,
    event_id: str = "sre-event-1",
    operation: str = "restart",
    event_type: str = "sre.ticket.updated",
) -> DomainEvent:
    return DomainEvent(
        id=event_id,
        type=event_type,
        source="sre-plugin-tests",
        subject="INF-1001",
        occurred_at=datetime(2026, 8, 17, tzinfo=UTC),
        correlation_id=f"correlation-{event_id}",
        idempotency_key=f"sre:{event_id}",
        tenant_id="tenant-1",
        data={
            "key": "INF-1001",
            "summary": f"{operation.title()} orders",
            "service": "orders",
            "environment": "prod",
            "operation": operation,
            "arguments": {"replicas": 2} if operation == "scale" else {},
        },
    )


def build_dispatcher(
    provider: CapabilityProvider,
    *,
    checkpointer: object | None = None,
) -> tuple[Dispatcher, CapabilityRegistry, AgentRegistry, FlowRegistry, TrackingPolicy]:
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
    policy = TrackingPolicy(provider.timeline)  # type: ignore[attr-defined]
    dispatcher = Dispatcher(
        flows=flows,
        runtime=LangGraphWorkflowRuntime(checkpointer=checkpointer),
        contexts=ExecutionContextFactory(
            capabilities=capabilities,
            agents=agents,
            policy=policy,
            observability=object(),
        ),
    )
    return dispatcher, capabilities, agents, flows, policy


def run_metadata(paused: RunResult, event: DomainEvent, flows: FlowRegistry) -> RunMetadata:
    return RunMetadata(
        run_id=paused.run_id,
        flow_name="sre",
        flow_version=flows.get("sre").metadata.version,
        thread_id=paused.run_id,
        correlation_id=event.correlation_id,
        tenant_id=event.tenant_id,
        status=RunStatus.PAUSED.value,
    )


def test_risky_action_cannot_execute_without_framework_approval() -> None:
    provider = RecordingSRECapabilities()
    dispatcher, _capabilities, _agents, _flows, policy = build_dispatcher(provider)

    paused = asyncio.run(dispatcher.dispatch(sre_event()))[0]

    assert paused.status is RunStatus.PAUSED
    assert paused.pause is not None
    assert paused.pause.approval is not None
    assert paused.pause.approval.action_hash == paused.output["action_hash"]
    assert paused.pause.approval.policy_version == policy.version
    assert paused.pause.approval.run_id == paused.run_id
    assert paused.pause.approval.tenant_id == "tenant-1"
    assert not provider.mutations
    assert "infra.execute" not in provider.timeline


def test_successful_approval_is_bound_and_policy_precedes_execution() -> None:
    provider = RecordingSRECapabilities()
    dispatcher, _capabilities, _agents, flows, policy = build_dispatcher(provider)
    event = sre_event()
    paused = asyncio.run(dispatcher.dispatch(event))[0]

    resumed = asyncio.run(
        dispatcher.resume(
            run_metadata(paused, event, flows),
            {"approved": True, "actor": "on-call", "reason": "Incident mitigation"},
        )
    )

    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.output["status"] == "completed"
    approval = resumed.output["approval"]
    assert approval["action_hash"] == resumed.output["action_hash"]
    assert approval["policy_version"] == policy.version
    assert approval["run_id"] == paused.run_id
    assert approval["thread_id"] == paused.run_id
    assert approval["correlation_id"] == event.correlation_id
    assert provider.timeline.index("policy.evaluate") < provider.timeline.index("infra.execute")
    assert provider.timeline.index("infra.execute") < provider.timeline.index("infra.verify")
    assert len(provider.mutations) == 1


def test_modifying_action_after_approval_request_invalidates_binding() -> None:
    provider = RecordingSRECapabilities()
    dispatcher, capabilities, agents, flows, policy = build_dispatcher(provider)
    event = sre_event()
    paused = asyncio.run(dispatcher.dispatch(event))[0]
    state = dict(paused.output)
    mutated = dict(state["action"])
    mutated["operation"] = "delete"
    state["action"] = mutated
    identity = ExecutionIdentity(
        run_id=paused.run_id,
        thread_id=paused.run_id,
        correlation_id=event.correlation_id,
        tenant_id=event.tenant_id,
    )
    context = ExecutionContext(
        identity=identity,
        capabilities=capabilities,
        agents=agents,
        policy=policy,
        observability=object(),
        metadata={"flow_name": flows.get("sre").metadata.name},
    )

    with pytest.raises(ApprovalActionMismatchError):
        _approval(
            state,
            NodeContext(
                execution=context,
                node_name="approval",
                resume_payload={
                    "approved": True,
                    "actor": "on-call",
                    "reason": "Approved original action",
                },
            ),
        )

    assert not provider.mutations


def test_duplicate_resume_is_idempotent_at_infrastructure_boundary() -> None:
    provider = RecordingSRECapabilities()
    dispatcher, _capabilities, _agents, flows, _policy = build_dispatcher(provider)
    event = sre_event(event_id="duplicate-resume")
    paused = asyncio.run(dispatcher.dispatch(event))[0]
    run = run_metadata(paused, event, flows)
    decision = {"approved": True, "actor": "on-call", "reason": "Bound approval"}

    first = asyncio.run(dispatcher.resume(run, decision))
    second = asyncio.run(dispatcher.resume(run, decision))

    assert first.status is RunStatus.SUCCEEDED
    assert second.status in {RunStatus.SUCCEEDED, RunStatus.FAILED}
    assert len(provider.mutations) == 1


def test_execution_failure_is_not_reported_as_verification_failure() -> None:
    provider = RecordingSRECapabilities(execution_failure=True)
    dispatcher, _capabilities, _agents, _flows, _policy = build_dispatcher(provider)

    result = asyncio.run(dispatcher.dispatch(sre_event(operation="inspect")))[0]

    assert result.status is RunStatus.SUCCEEDED
    assert result.output["status"] == "execution_failed"
    assert result.output["outcome"]["phase"] == "execution"
    assert "verified" not in result.output
    assert "infra.verify" not in provider.timeline
    assert provider.memory_records


def test_verification_failure_is_distinct_from_successful_execution() -> None:
    provider = RecordingSRECapabilities(verification_failure=True)
    dispatcher, _capabilities, _agents, _flows, _policy = build_dispatcher(provider)

    result = asyncio.run(dispatcher.dispatch(sre_event(operation="inspect")))[0]

    assert result.status is RunStatus.SUCCEEDED
    assert result.output["execution_result"]["success"] is True
    assert result.output["verified"] is False
    assert result.output["status"] == "verification_failed"
    assert result.output["outcome"]["phase"] == "verification"
    assert result.output["verification_error"] == "health check failed"


def test_notification_is_idempotent_audit_and_memory_follows_known_outcome() -> None:
    provider = RecordingSRECapabilities()
    dispatcher, _capabilities, _agents, _flows, _policy = build_dispatcher(provider)
    event = sre_event(operation="inspect", event_id="audit-success")

    first = asyncio.run(dispatcher.dispatch(event))[0]
    second = asyncio.run(dispatcher.dispatch(event))[0]

    assert first.output["status"] == second.output["status"] == "completed"
    assert len(provider.notifications) == 1
    notification = provider.notifications["sre:audit-success:sre-outcome"]
    assert notification["audit"] == {
        "ticket_key": "INF-1001",
        "action_hash": first.output["action_hash"],
        "status": "completed",
        "phase": "verification",
    }
    assert len(provider.memory_records) == 1
    memory = provider.memory_records["sre:audit-success:sre-memory"]
    assert memory["content"]["outcome"]["status"] == "completed"
    assert provider.timeline.index("infra.verify") < provider.timeline.index(
        "notification.send"
    )
    assert provider.timeline.index("notification.send") < provider.timeline.index(
        "memory.record"
    )


def test_optional_knowledge_memory_and_notification_can_be_absent() -> None:
    provider = RecordingSRECapabilities(
        include_knowledge=False,
        include_recall=False,
        include_record=False,
        include_notification=False,
    )
    dispatcher, _capabilities, _agents, _flows, _policy = build_dispatcher(provider)

    result = asyncio.run(dispatcher.dispatch(sre_event(operation="inspect")))[0]

    assert result.status is RunStatus.SUCCEEDED
    assert result.output["status"] == "completed"
    assert result.output["evidence"] == []
    assert result.output["memory_available"] is False
    assert result.output["memory_recorded"] is False
    assert not any(name.startswith("memory.") for name in provider.timeline)
    assert "notification.send" not in provider.timeline


def test_plugin_registration_events_and_dependency_boundary() -> None:
    provider = RecordingSRECapabilities()
    _dispatcher, capabilities, agents, flows, _policy = build_dispatcher(provider)

    assert dict(agents.list()) == {}
    flow = flows.get("sre")
    assert isinstance(flow, SREFlow)
    assert flow.metadata.event_types == frozenset(
        {"sre.ticket.updated", "sre.action.requested"}
    )
    assert flow.metadata.required_capabilities == REQUIRED_CAPABILITIES
    assert flow.metadata.optional_capabilities == frozenset(
        {"knowledge.search", "memory.recall", "memory.record", "notification.send"}
    )
    assert flow.accepts(sre_event(event_type="sre.action.requested"))
    assert capabilities.has("infra.execute")

    forbidden: list[str] = []
    forbidden_prefixes = (
        "lang" + "chain",
        "langgraph",
        "sre_skills",
        "sre-skills",
        "subprocess",
        "shlex",
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
