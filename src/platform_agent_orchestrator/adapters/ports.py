"""Dependency inversion boundary between graphs and domain systems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from platform_agent_orchestrator.contracts import (
    ActionRequest,
    ActionResult,
    AgentDecision,
    DomainEvent,
    EvidenceRef,
    KnowledgeArtifact,
)


class KnowledgePort(Protocol):
    def search(self, query: str, *, limit: int = 8) -> list[EvidenceRef]: ...


class ReasoningPort(Protocol):
    def assess_alert(self, alert: dict[str, Any], evidence: list[EvidenceRef]) -> AgentDecision: ...

    def answer_engineering(
        self, role: str, question: str, evidence: list[EvidenceRef]
    ) -> AgentDecision: ...

    def plan_sre(
        self, ticket: dict[str, Any], evidence: list[EvidenceRef]
    ) -> list[ActionRequest]: ...


class ExtractionPort(Protocol):
    def extract(
        self, surface: str, event: DomainEvent, changed_files: list[str]
    ) -> list[KnowledgeArtifact]: ...


class PublicationPort(Protocol):
    def publish(self, subject: str, revision: str, artifacts: list[KnowledgeArtifact]) -> str: ...


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


@dataclass(frozen=True)
class PlatformServices:
    knowledge: KnowledgePort
    reasoner: ReasoningPort
    extractor: ExtractionPort
    publisher: PublicationPort
    notifier: NotificationPort
    actions: ActionPort
