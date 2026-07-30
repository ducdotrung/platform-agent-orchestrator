"""Deterministic in-memory adapters for demos and tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from platform_agent_orchestrator.contracts import (
    ActionRequest,
    ActionResult,
    AgentDecision,
    DecisionStatus,
    DomainEvent,
    EvidenceKind,
    EvidenceRef,
    KnowledgeArtifact,
    RiskLevel,
)

from .ports import NotificationPort, PlatformServices


def stable_id(*parts: str) -> str:
    joined = "|".join(parts).encode()
    return hashlib.sha256(joined).hexdigest()[:16]


@dataclass
class DemoKnowledge:
    def search(self, query: str, *, limit: int = 8) -> list[EvidenceRef]:
        query_lower = query.lower()
        evidence = [
            EvidenceRef(
                id="service-edge-order-payment",
                kind=EvidenceKind.GRAPH,
                source="service-graph-toolkit",
                locator="projects/demo/inventory.yaml#order-to-payment",
                revision="demo-rev-1",
                summary="order-service calls payment-service during checkout",
                confidence=0.98,
            ),
            EvidenceRef(
                id="runbook-payment-timeout",
                kind=EvidenceKind.DOCUMENT,
                source="sre-skills",
                locator="runbooks/payment-timeout.md",
                revision="demo-rev-1",
                summary="Payment timeout runbook checks dependency health before restart",
                confidence=0.95,
            ),
            EvidenceRef(
                id="config-payment-timeout",
                kind=EvidenceKind.CONFIG,
                source="cicd-config",
                locator="helm/payment/values-prod.yaml#requestTimeout",
                revision="demo-rev-1",
                summary="Production payment client timeout is five seconds",
                confidence=1.0,
            ),
        ]
        ranked = [
            item
            for item in evidence
            if any(token in item.summary.lower() for token in query_lower.split())
        ]
        return (ranked or evidence)[:limit]


@dataclass
class DemoReasoner:
    def assess_alert(self, alert: dict[str, Any], evidence: list[EvidenceRef]) -> AgentDecision:
        priority = alert.get("priority", "P3")
        status = DecisionStatus.PROCEED if priority in {"P0", "P1"} else DecisionStatus.REVIEW
        return AgentDecision(
            status=status,
            summary=f"{priority} alert affects the checkout dependency path",
            confidence=0.91 if evidence else 0.55,
            reasons=["Alert volume is actionable", "A downstream dependency is documented"],
            evidence_ids=[item.id for item in evidence],
        )

    def answer_engineering(
        self, role: str, question: str, evidence: list[EvidenceRef]
    ) -> AgentDecision:
        guidance = {
            "developer": "Update the payment client and preserve the existing timeout boundary.",
            "qa": "Cover checkout success, dependency timeout, retry, and degraded-mode paths.",
            "product": "The change can affect checkout completion and payment availability.",
        }
        return AgentDecision(
            status=DecisionStatus.PROCEED,
            summary=guidance[role],
            confidence=0.9,
            reasons=[f"Answered as the {role} view", f"Question: {question}"],
            evidence_ids=[item.id for item in evidence],
        )

    def plan_sre(self, ticket: dict[str, Any], evidence: list[EvidenceRef]) -> list[ActionRequest]:
        target = str(ticket.get("service", "unknown-service"))
        operation = str(ticket.get("operation", "inspect"))
        risk = RiskLevel.SAFE if operation in {"inspect", "logs", "status"} else RiskLevel.RISKY
        return [
            ActionRequest(
                action=operation,
                target=target,
                parameters={"environment": ticket.get("environment", "dev")},
                risk=risk,
                idempotency_key=f"{ticket.get('key', 'ticket')}:{operation}:{target}",
            )
        ]


@dataclass
class DemoExtractor:
    def extract(
        self, surface: str, event: DomainEvent, changed_files: list[str]
    ) -> list[KnowledgeArtifact]:
        relevant = {
            "code": [
                path for path in changed_files if path.endswith((".py", ".ts", ".java", ".go"))
            ],
            "config": [
                path for path in changed_files if path.endswith((".yaml", ".yml", ".json", ".tf"))
            ],
            "document": [path for path in changed_files if path.endswith((".md", ".adoc"))],
        }[surface]
        if not relevant:
            return []
        revision = str(event.payload.get("revision", "unknown"))
        artifact_id = stable_id(event.subject, revision, surface)
        return [
            KnowledgeArtifact(
                id=artifact_id,
                artifact_type=surface,
                subject=event.subject,
                revision=revision,
                content={"changed_files": relevant, "summary": f"Refreshed {surface} knowledge"},
                evidence=[
                    EvidenceRef(
                        id=f"evidence-{artifact_id}",
                        kind=EvidenceKind(surface),
                        source=event.source,
                        locator=path,
                        revision=revision,
                        summary=f"Changed {surface} source: {path}",
                    )
                    for path in relevant
                ],
            )
        ]


@dataclass
class DemoPublisher:
    publications: list[dict[str, Any]] = field(default_factory=list)

    def publish(self, subject: str, revision: str, artifacts: list[KnowledgeArtifact]) -> str:
        snapshot_id = stable_id(subject, revision, *(artifact.id for artifact in artifacts))
        self.publications.append(
            {
                "snapshot_id": snapshot_id,
                "subject": subject,
                "revision": revision,
                "artifacts": artifacts,
            }
        )
        return snapshot_id


@dataclass
class DemoNotifier:
    messages: dict[str, dict[str, str]] = field(default_factory=dict)

    def send(
        self,
        channel: str,
        message: str,
        *,
        idempotency_key: str,
        run_id: str | None = None,
    ) -> str:
        receipt = f"notification-{stable_id(channel, idempotency_key)}"
        self.messages.setdefault(
            idempotency_key, {"receipt": receipt, "channel": channel, "message": message}
        )
        return self.messages[idempotency_key]["receipt"]


@dataclass
class DemoActions:
    results: dict[str, ActionResult] = field(default_factory=dict)

    def execute(self, request: ActionRequest) -> ActionResult:
        if request.idempotency_key not in self.results:
            self.results[request.idempotency_key] = ActionResult(
                request=request,
                success=True,
                summary=f"Demo execution completed: {request.action} on {request.target}",
                evidence=[
                    EvidenceRef(
                        kind=EvidenceKind.ALERT,
                        source="demo-action-adapter",
                        locator=f"actions/{request.idempotency_key}",
                        summary="Recorded deterministic demo action",
                    )
                ],
            )
        return self.results[request.idempotency_key]

    def verify(self, result: ActionResult) -> bool:
        return result.success


@dataclass
class DemoPlatformServices:
    knowledge: DemoKnowledge = field(default_factory=DemoKnowledge)
    reasoner: DemoReasoner = field(default_factory=DemoReasoner)
    extractor: DemoExtractor = field(default_factory=DemoExtractor)
    publisher: DemoPublisher = field(default_factory=DemoPublisher)
    notifier: DemoNotifier = field(default_factory=DemoNotifier)
    actions: DemoActions = field(default_factory=DemoActions)

    def as_services(self, *, notifier: NotificationPort | None = None) -> PlatformServices:
        return PlatformServices(
            knowledge=self.knowledge,
            reasoner=self.reasoner,
            extractor=self.extractor,
            publisher=self.publisher,
            notifier=notifier or self.notifier,
            actions=self.actions,
        )
