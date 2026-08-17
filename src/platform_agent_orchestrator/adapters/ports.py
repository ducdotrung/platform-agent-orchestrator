"""Dependency inversion boundary between graphs and domain systems."""

from __future__ import annotations

from typing import Any, Protocol

from platform_agent_orchestrator.contracts import (
    ActionRequest,
    ActionResult,
    AgentDecision,
    EvidenceRef,
    KnowledgeArtifact,
)


class KnowledgePort(Protocol):
    def search(self, query: str, *, limit: int = 8) -> list[EvidenceRef]: ...


class AlertClassificationPort(Protocol):
    def classify(self, alert: dict[str, Any]) -> dict[str, Any]: ...


class ReasoningPort(Protocol):
    def assess_alert(self, alert: dict[str, Any], evidence: list[EvidenceRef]) -> AgentDecision: ...


class ExtractionPort(Protocol):
    def extract(
        self,
        surface: str,
        *,
        subject: str,
        source: str,
        revision: str,
        changed_files: list[str],
    ) -> list[KnowledgeArtifact]: ...


class PublicationPort(Protocol):
    def publish(
        self,
        subject: str,
        revision: str,
        artifacts: list[KnowledgeArtifact],
        *,
        idempotency_key: str,
    ) -> str: ...


class NotificationPort(Protocol):
    def send(
        self,
        channel: str,
        message: str,
        *,
        idempotency_key: str,
        run_id: str | None = None,
    ) -> str: ...


class ActionPort(Protocol):
    def execute(self, request: ActionRequest) -> ActionResult: ...

    def verify(self, result: ActionResult) -> bool: ...
