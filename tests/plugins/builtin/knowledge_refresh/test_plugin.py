from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platform_agent_orchestrator.adapters.demo import DemoPlatformServices
from platform_agent_orchestrator.adapters.demo_capabilities import (
    DemoKnowledgeRefreshCapabilityProvider,
)
from platform_agent_orchestrator.core import (
    CapabilityRequest,
    CapabilityResult,
    DomainEvent,
    EvidenceRef,
    ExecutionContext,
    KnowledgeArtifact,
)
from platform_agent_orchestrator.plugins.builtin.knowledge_refresh import (
    KnowledgeRefreshFlow,
    plugin,
)
from platform_agent_orchestrator.registry import (
    AgentRegistry,
    CapabilityRegistry,
    FlowRegistry,
    validate_registry,
)
from platform_agent_orchestrator.runtime import RunResult, RunStatus
from platform_agent_orchestrator.runtime.context import ExecutionContextFactory
from platform_agent_orchestrator.runtime.dispatcher import Dispatcher
from platform_agent_orchestrator.runtime.langgraph import LangGraphWorkflowRuntime
from platform_agent_orchestrator.sdk import PluginContext

REQUIRED_CAPABILITIES = frozenset(
    {
        "knowledge.extract.code",
        "knowledge.extract.config",
        "knowledge.extract.docs",
        "knowledge.publish",
    }
)
PLUGIN_ROOT = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "platform_agent_orchestrator"
    / "plugins"
    / "builtin"
    / "knowledge_refresh"
)


@dataclass
class RecordingRefreshCapabilities:
    include_memory: bool = False
    synchronize_extractions: bool = False
    failed_capability: str | None = None
    invalid_provenance: bool = False
    requests: list[CapabilityRequest] = field(default_factory=list)
    started_extractions: set[str] = field(default_factory=set)
    extraction_barrier: asyncio.Event = field(default_factory=asyncio.Event)
    publications: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_records: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def capabilities(self) -> frozenset[str]:
        if self.include_memory:
            return REQUIRED_CAPABILITIES | frozenset({"memory.record"})
        return REQUIRED_CAPABILITIES

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult:
        del context
        self.requests.append(request)
        if request.capability.startswith("knowledge.extract."):
            return await self._extract(request)
        if request.capability == "knowledge.publish":
            return self._publish(request)
        if request.capability == "memory.record" and self.include_memory:
            key = str(request.arguments["idempotency_key"])
            self.memory_records.setdefault(key, dict(request.arguments))
            return CapabilityResult(success=True, data={"receipt": f"memory:{key}"})
        return CapabilityResult(success=False, error="unsupported test capability")

    async def _extract(self, request: CapabilityRequest) -> CapabilityResult:
        capability = request.capability
        self.started_extractions.add(capability)
        if len(self.started_extractions) == 3:
            self.extraction_barrier.set()
        if self.synchronize_extractions:
            await asyncio.wait_for(self.extraction_barrier.wait(), timeout=1)
        if capability == self.failed_capability:
            return CapabilityResult(success=False, error=f"failed {capability}")

        surface = capability.rsplit(".", maxsplit=1)[-1]
        revision = str(request.arguments["revision"])
        evidence_revision = None if self.invalid_provenance and surface == "code" else revision
        artifact = KnowledgeArtifact(
            id=f"artifact-{surface}-{revision}",
            kind=surface,
            revision=revision,
            content={"changed_files": request.arguments["changed_files"]},
            evidence=[
                EvidenceRef(
                    kind=surface,
                    locator=str(request.arguments["changed_files"][0]),
                    revision=evidence_revision,
                )
            ],
        )
        return CapabilityResult(
            success=True,
            data={"artifacts": [artifact.model_dump(mode="json")]},
        )

    def _publish(self, request: CapabilityRequest) -> CapabilityResult:
        key = str(request.arguments["idempotency_key"])
        publication = dict(request.arguments)
        previous = self.publications.setdefault(key, publication)
        if previous != publication:
            return CapabilityResult(
                success=False,
                error="idempotency key reused with different content",
            )
        return CapabilityResult(
            success=True,
            data={"snapshot_id": f"snapshot:{key}"},
        )


class Policies:
    def register(self, name: str, policy: object) -> None:
        del name, policy


def merged_event(*, categories: list[str] | None = None) -> DomainEvent:
    data: dict[str, Any] = {
        "revision": "abc123",
        "changed_files": [
            "src/payment/client.py",
            "helm/payment/values.yaml",
            "docs/payment-contract.md",
        ],
    }
    if categories is not None:
        data["change_categories"] = categories
    return DomainEvent(
        id="refresh-event-1",
        type="scm.pull_request.merged",
        source="scm-tests",
        subject="payment-service",
        occurred_at=datetime(2026, 8, 17, tzinfo=UTC),
        correlation_id="refresh-correlation-1",
        idempotency_key="scm:payment-service:abc123",
        tenant_id="tenant-1",
        data=data,
    )


def build_dispatcher(
    provider: object,
) -> tuple[Dispatcher, CapabilityRegistry, AgentRegistry, FlowRegistry]:
    capabilities = CapabilityRegistry()
    capabilities.register(provider)  # type: ignore[arg-type]
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


def dispatch(provider: object, event: DomainEvent | None = None) -> RunResult:
    dispatcher, _capabilities, _agents, _flows = build_dispatcher(provider)
    results = asyncio.run(dispatcher.dispatch(event or merged_event()))
    assert len(results) == 1
    return results[0]


def test_three_extraction_branches_execute_truly_in_parallel() -> None:
    provider = RecordingRefreshCapabilities(synchronize_extractions=True)

    result = dispatch(provider)

    assert result.status is RunStatus.SUCCEEDED
    assert provider.started_extractions == {
        "knowledge.extract.code",
        "knowledge.extract.config",
        "knowledge.extract.docs",
    }
    assert result.output["status"] == "published"
    assert {item["kind"] for item in result.output["artifacts"]} == {
        "code",
        "config",
        "docs",
    }


def test_failed_extraction_branch_fails_run_without_publication() -> None:
    provider = RecordingRefreshCapabilities(
        failed_capability="knowledge.extract.config"
    )

    result = dispatch(provider)

    assert result.status is RunStatus.FAILED
    assert result.error is not None and "knowledge.extract.config" in result.error
    assert not provider.publications
    assert not any(
        request.capability == "knowledge.publish" for request in provider.requests
    )


def test_provenance_failure_blocks_publication() -> None:
    provider = RecordingRefreshCapabilities(invalid_provenance=True)

    result = dispatch(provider)

    assert result.status is RunStatus.SUCCEEDED
    assert result.output["status"] == "validation_failed"
    assert result.output["validation_errors"] == [
        "artifact contains unrevisioned evidence: artifact-code-abc123"
    ]
    assert not provider.publications


def test_demo_publication_is_atomic_and_idempotent() -> None:
    demo = DemoPlatformServices()
    provider = DemoKnowledgeRefreshCapabilityProvider(demo.extractor, demo.publisher)
    dispatcher, _capabilities, _agents, _flows = build_dispatcher(provider)
    event = merged_event()

    first = asyncio.run(dispatcher.dispatch(event))[0]
    second = asyncio.run(dispatcher.dispatch(event))[0]

    assert first.status is RunStatus.SUCCEEDED
    assert second.status is RunStatus.SUCCEEDED
    assert first.output["snapshot_id"] == second.output["snapshot_id"]
    assert len(demo.publisher.publications) == 1
    publication = demo.publisher.publications[0]
    assert publication["idempotency_key"] == (
        "scm:payment-service:abc123:knowledge-publish"
    )
    assert {artifact.artifact_type for artifact in publication["artifacts"]} == {
        "code",
        "config",
        "document",
    }


def test_missing_optional_memory_does_not_block_significant_refresh() -> None:
    provider = RecordingRefreshCapabilities(include_memory=False)

    result = dispatch(provider, merged_event(categories=["architecture-decision"]))

    assert result.status is RunStatus.SUCCEEDED
    assert result.output["status"] == "published"
    assert result.output["memory_worthy"] is True
    assert result.output["memory_recorded"] is False
    assert not any(request.capability == "memory.record" for request in provider.requests)


def test_memory_record_is_selective_and_idempotent() -> None:
    provider = RecordingRefreshCapabilities(include_memory=True)

    trivial = dispatch(provider)
    significant = dispatch(provider, merged_event(categories=["breaking-change"]))

    assert trivial.output["memory_worthy"] is False
    assert trivial.output["memory_recorded"] is False
    assert significant.output["memory_recorded"] is True
    assert len(provider.memory_records) == 1


def test_plugin_registration_and_dependency_boundary() -> None:
    provider = RecordingRefreshCapabilities()
    _dispatcher, capabilities, agents, flows = build_dispatcher(provider)

    assert dict(agents.list()) == {}
    flow = flows.get("knowledge-refresh")
    assert isinstance(flow, KnowledgeRefreshFlow)
    assert flow.metadata.event_types == frozenset({"scm.pull_request.merged"})
    assert flow.metadata.required_capabilities == REQUIRED_CAPABILITIES
    assert flow.metadata.optional_capabilities == frozenset({"memory.record"})
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
