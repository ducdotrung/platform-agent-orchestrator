"""Merged-PR knowledge refresh with parallel deterministic extraction."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from platform_agent_orchestrator.adapters.ports import PlatformServices
from platform_agent_orchestrator.contracts import KnowledgeArtifact

from .common import load_event


class RefreshState(TypedDict, total=False):
    event: dict[str, Any]
    run_id: str
    changed_files: list[str]
    surfaces: list[str]
    artifacts: Annotated[list[dict[str, Any]], operator.add]
    validation_errors: list[str]
    snapshot_id: str
    notification_receipt: str
    status: str


def build_knowledge_refresh_graph(
    services: PlatformServices, *, checkpointer: Any | None = None
) -> Any:
    def determine_scope(state: RefreshState) -> dict[str, Any]:
        event = load_event(state)
        changed_files = [str(path) for path in event.payload.get("changed_files", [])]
        surfaces: list[str] = []
        if any(path.endswith((".py", ".ts", ".java", ".go")) for path in changed_files):
            surfaces.append("code")
        if any(path.endswith((".yaml", ".yml", ".json", ".tf")) for path in changed_files):
            surfaces.append("config")
        if any(path.endswith((".md", ".adoc")) for path in changed_files):
            surfaces.append("document")
        return {"changed_files": changed_files, "surfaces": surfaces, "artifacts": []}

    def extractor(surface: str):
        def run(state: RefreshState) -> dict[str, Any]:
            if surface not in state["surfaces"]:
                return {"artifacts": []}
            event = load_event(state)
            artifacts = services.extractor.extract(surface, event, state["changed_files"])
            return {"artifacts": [item.model_dump(mode="json") for item in artifacts]}

        return run

    def validate(state: RefreshState) -> dict[str, Any]:
        artifacts = [KnowledgeArtifact.model_validate(item) for item in state.get("artifacts", [])]
        errors: list[str] = []
        seen: set[str] = set()
        for artifact in artifacts:
            if artifact.id in seen:
                errors.append(f"Duplicate artifact id: {artifact.id}")
            seen.add(artifact.id)
            if not artifact.evidence:
                errors.append(f"Artifact has no evidence: {artifact.id}")
            if any(not ref.revision for ref in artifact.evidence):
                errors.append(f"Artifact contains unrevisioned evidence: {artifact.id}")
        return {"validation_errors": errors}

    def after_validation(state: RefreshState) -> str:
        return "failed" if state.get("validation_errors") else "publish"

    def publish(state: RefreshState) -> dict[str, Any]:
        event = load_event(state)
        revision = str(event.payload.get("revision", "unknown"))
        artifacts = [KnowledgeArtifact.model_validate(item) for item in state.get("artifacts", [])]
        snapshot_id = services.publisher.publish(event.subject, revision, artifacts)
        return {"snapshot_id": snapshot_id}

    def notify(state: RefreshState) -> dict[str, Any]:
        event = load_event(state)
        message = f"Published knowledge snapshot {state['snapshot_id']} for {event.subject}"
        receipt = services.notifier.send(
            "platform-knowledge",
            message,
            idempotency_key=f"{event.idempotency_key}:snapshot",
            run_id=state.get("run_id", event.correlation_id),
        )
        return {"notification_receipt": receipt, "status": "published"}

    def failed(state: RefreshState) -> dict[str, Any]:
        return {"status": "validation_failed"}

    builder = StateGraph(RefreshState)
    builder.add_node("determine_scope", determine_scope)
    builder.add_node("extract_code", extractor("code"))
    builder.add_node("extract_config", extractor("config"))
    builder.add_node("extract_document", extractor("document"))
    builder.add_node("validate", validate)
    builder.add_node("publish", publish)
    builder.add_node("notify", notify)
    builder.add_node("failed", failed)
    builder.add_edge(START, "determine_scope")
    for node in ("extract_code", "extract_config", "extract_document"):
        builder.add_edge("determine_scope", node)
    builder.add_edge(["extract_code", "extract_config", "extract_document"], "validate")
    builder.add_conditional_edges(
        "validate", after_validation, {"failed": "failed", "publish": "publish"}
    )
    builder.add_edge("publish", "notify")
    builder.add_edge("notify", END)
    builder.add_edge("failed", END)
    return builder.compile(checkpointer=checkpointer)
