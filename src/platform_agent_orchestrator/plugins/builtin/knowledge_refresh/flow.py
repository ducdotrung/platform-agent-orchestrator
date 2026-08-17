"""Runtime-neutral knowledge refresh flow."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Protocol, TypedDict, cast

from platform_agent_orchestrator.core.capabilities import CapabilityRequest, CapabilityResult
from platform_agent_orchestrator.core.context import ExecutionContext
from platform_agent_orchestrator.core.models import KnowledgeArtifact
from platform_agent_orchestrator.sdk.flow import (
    FLOW_END,
    BaseFlow,
    ConditionalRoute,
    EdgeSpec,
    FlowDefinition,
    FlowMetadata,
    JoinSpec,
    NodeSpec,
)
from platform_agent_orchestrator.sdk.nodes import NodeContext

SURFACE_CAPABILITIES = {
    "code": "knowledge.extract.code",
    "config": "knowledge.extract.config",
    "docs": "knowledge.extract.docs",
}
SURFACE_SUFFIXES = {
    "code": (".py", ".ts", ".java", ".go"),
    "config": (".yaml", ".yml", ".json", ".tf"),
    "docs": (".md", ".adoc"),
}
MEMORY_WORTHY_CATEGORIES = frozenset(
    {
        "architecture",
        "architecture-decision",
        "breaking-change",
        "incident-workaround",
        "operational-behavior",
    }
)


class KnowledgeRefreshState(TypedDict, total=False):
    event: dict[str, Any]
    run_id: str
    subject: str
    source: str
    revision: str
    publication_key: str
    changed_files: list[str]
    surfaces: list[str]
    artifacts: Annotated[list[dict[str, Any]], operator.add]
    validation_errors: list[str]
    memory_worthy: bool
    memory_recorded: bool
    memory_record_error: str
    snapshot_id: str
    status: str


class CapabilityAccess(Protocol):
    def has(self, capability: str) -> bool: ...

    async def invoke(
        self,
        request: CapabilityRequest,
        *,
        context: ExecutionContext,
    ) -> CapabilityResult: ...


class KnowledgeRefreshFlow(BaseFlow):
    metadata = FlowMetadata(
        name="knowledge-refresh",
        version="2.0.0",
        description="Refresh revisioned knowledge after a merged pull request.",
        event_types=frozenset({"scm.pull_request.merged"}),
        required_capabilities=frozenset(SURFACE_CAPABILITIES.values())
        | frozenset({"knowledge.publish"}),
        optional_capabilities=frozenset({"memory.record"}),
        tags=frozenset({"builtin", "knowledge", "refresh"}),
    )

    def define(self) -> FlowDefinition:
        extractors = tuple(f"extract_{surface}" for surface in SURFACE_CAPABILITIES)
        return FlowDefinition(
            state_schema=KnowledgeRefreshState,
            entrypoint="detect_surfaces",
            nodes=[
                NodeSpec("detect_surfaces", _detect_surfaces),
                NodeSpec("extract_code", _extractor("code")),
                NodeSpec("extract_config", _extractor("config")),
                NodeSpec("extract_docs", _extractor("docs")),
                NodeSpec("validate_provenance", _validate_provenance),
                NodeSpec("publish", _publish),
                NodeSpec("record_memory", _record_memory),
                NodeSpec("complete", _complete),
                NodeSpec("provenance_failed", _provenance_failed),
            ],
            edges=[
                *(EdgeSpec("detect_surfaces", extractor) for extractor in extractors),
                EdgeSpec("publish", "record_memory"),
                EdgeSpec("record_memory", "complete"),
                EdgeSpec("complete", FLOW_END),
                EdgeSpec("provenance_failed", FLOW_END),
            ],
            joins=[JoinSpec(extractors, "validate_provenance")],
            conditional_routes=[
                ConditionalRoute(
                    source="validate_provenance",
                    router=_after_validation,
                    routes={"publish": "publish", "failed": "provenance_failed"},
                )
            ],
        )


def _detect_surfaces(state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    event = state.get("event")
    if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
        raise ValueError("knowledge refresh requires a runtime-neutral event object")
    data = event["data"]
    revision = str(data.get("revision", "")).strip()
    if not revision:
        raise ValueError("knowledge refresh requires a source revision")
    subject = str(event.get("subject") or "").strip()
    if not subject:
        raise ValueError("knowledge refresh requires an event subject")
    raw_files = data.get("changed_files", [])
    if not isinstance(raw_files, list):
        raise ValueError("changed_files must be a list")
    changed_files = [str(path) for path in raw_files]
    surfaces = [
        surface
        for surface, suffixes in SURFACE_SUFFIXES.items()
        if any(path.endswith(suffixes) for path in changed_files)
    ]
    categories = {
        str(category).strip().lower().replace("_", "-")
        for category in data.get("change_categories", [])
    }
    memory_worthy = data.get("memory_worthy") is True or bool(
        categories & MEMORY_WORTHY_CATEGORIES
    )
    return {
        "subject": subject,
        "source": str(event.get("source", "unknown")),
        "revision": revision,
        "publication_key": f"{event['idempotency_key']}:knowledge-publish",
        "changed_files": changed_files,
        "surfaces": surfaces,
        "artifacts": [],
        "memory_worthy": memory_worthy,
    }


def _extractor(surface: str):
    async def extract(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
        if surface not in state["surfaces"]:
            return {"artifacts": []}
        capabilities = cast(CapabilityAccess, node.execution.capabilities)
        relevant_files = [
            path
            for path in state["changed_files"]
            if path.endswith(SURFACE_SUFFIXES[surface])
        ]
        capability = SURFACE_CAPABILITIES[surface]
        result = await capabilities.invoke(
            CapabilityRequest(
                capability=capability,
                operation="extract",
                arguments={
                    "subject": state["subject"],
                    "source": state["source"],
                    "revision": state["revision"],
                    "changed_files": relevant_files,
                },
            ),
            context=node.execution,
        )
        if not result.success:
            raise RuntimeError(result.error or f"{capability} failed")
        artifacts = _artifact_items(result.data)
        return {
            "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts]
        }

    return extract


def _artifact_items(data: dict[str, Any]) -> list[KnowledgeArtifact]:
    raw_artifacts = data.get("artifacts", [])
    if not isinstance(raw_artifacts, list):
        raise TypeError("extraction capability artifacts must be a list")
    return [KnowledgeArtifact.model_validate(item) for item in raw_artifacts]


def _validate_provenance(
    state: dict[str, Any],
    _node: NodeContext,
) -> dict[str, Any]:
    artifacts = [
        KnowledgeArtifact.model_validate(item) for item in state.get("artifacts", [])
    ]
    expected_revision = state["revision"]
    expected_kinds = set(state["surfaces"])
    seen: set[str] = set()
    errors: list[str] = []
    for artifact in artifacts:
        if artifact.id in seen:
            errors.append(f"duplicate artifact id: {artifact.id}")
        seen.add(artifact.id)
        if artifact.kind not in expected_kinds:
            errors.append(f"unexpected artifact kind: {artifact.id}:{artifact.kind}")
        if artifact.revision != expected_revision:
            errors.append(f"artifact revision mismatch: {artifact.id}")
        if not artifact.evidence:
            errors.append(f"artifact has no evidence: {artifact.id}")
        for evidence in artifact.evidence:
            if not evidence.revision:
                errors.append(f"artifact contains unrevisioned evidence: {artifact.id}")
            elif evidence.revision != expected_revision:
                errors.append(f"evidence revision mismatch: {artifact.id}")
    return {"validation_errors": errors}


def _after_validation(state: dict[str, Any]) -> str:
    return "failed" if state.get("validation_errors") else "publish"


async def _publish(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="knowledge.publish",
            operation="publish_atomic",
            arguments={
                "subject": state["subject"],
                "revision": state["revision"],
                "idempotency_key": state["publication_key"],
                "artifacts": state.get("artifacts", []),
            },
        ),
        context=node.execution,
    )
    if not result.success:
        raise RuntimeError(result.error or "knowledge.publish failed")
    snapshot_id = str(result.data.get("snapshot_id", "")).strip()
    if not snapshot_id:
        raise RuntimeError("knowledge.publish returned no snapshot_id")
    return {"snapshot_id": snapshot_id}


async def _record_memory(state: dict[str, Any], node: NodeContext) -> dict[str, Any]:
    capabilities = cast(CapabilityAccess, node.execution.capabilities)
    if not state["memory_worthy"] or not capabilities.has("memory.record"):
        return {"memory_recorded": False}
    artifacts = [
        KnowledgeArtifact.model_validate(item) for item in state.get("artifacts", [])
    ]
    result = await capabilities.invoke(
        CapabilityRequest(
            capability="memory.record",
            operation="record",
            arguments={
                "idempotency_key": f"{state['publication_key']}:memory",
                "subject": state["subject"],
                "revision": state["revision"],
                "snapshot_id": state["snapshot_id"],
                "artifacts": [
                    {"id": artifact.id, "kind": artifact.kind} for artifact in artifacts
                ],
            },
        ),
        context=node.execution,
    )
    if not result.success:
        return {
            "memory_recorded": False,
            "memory_record_error": result.error or "memory.record failed",
        }
    return {"memory_recorded": True}


def _complete(_state: dict[str, Any], _node: NodeContext) -> dict[str, Any]:
    return {"status": "published"}


def _provenance_failed(
    _state: dict[str, Any],
    _node: NodeContext,
) -> dict[str, Any]:
    return {"status": "validation_failed", "memory_recorded": False}
