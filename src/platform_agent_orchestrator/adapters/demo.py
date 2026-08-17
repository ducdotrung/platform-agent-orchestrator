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
    EvidenceKind,
    EvidenceRef,
    KnowledgeArtifact,
)


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
class DemoAlertClassifier:
    """Demo-only alert policy standing in for the sre-alert-agent capability."""

    def classify(self, alert: dict[str, Any]) -> dict[str, Any]:
        title = str(alert.get("title", "")).lower()
        known_noise = ("client disconnected", "cancelled request", "health check")
        suppressed = any(marker in title for marker in known_noise) and int(
            alert.get("count", 1)
        ) < 100
        if suppressed:
            return {
                "suppressed": True,
                "suppression_reason": "Matched a bounded demo noise rule",
                "classification": "known-noise",
            }

        severity = str(alert.get("severity", "warning"))
        users = int(alert.get("users", 0))
        count = int(alert.get("count", 1))
        if severity in {"fatal", "critical"} or users >= 50:
            priority = "P0"
        elif count >= 100 or users >= 10:
            priority = "P1"
        elif count >= 20:
            priority = "P2"
        else:
            priority = "P3"
        return {
            "suppressed": False,
            "classification": "actionable",
            "priority": priority,
        }


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


@dataclass
class DemoExtractor:
    def extract(
        self,
        surface: str,
        *,
        subject: str,
        source: str,
        revision: str,
        changed_files: list[str],
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
        artifact_id = stable_id(subject, revision, surface)
        return [
            KnowledgeArtifact(
                id=artifact_id,
                artifact_type=surface,
                subject=subject,
                revision=revision,
                content={"changed_files": relevant, "summary": f"Refreshed {surface} knowledge"},
                evidence=[
                    EvidenceRef(
                        id=f"evidence-{artifact_id}",
                        kind=EvidenceKind(surface),
                        source=source,
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
    _publications_by_key: dict[str, tuple[str, str]] = field(default_factory=dict)

    def publish(
        self,
        subject: str,
        revision: str,
        artifacts: list[KnowledgeArtifact],
        *,
        idempotency_key: str,
    ) -> str:
        fingerprint = stable_id(
            subject,
            revision,
            *(
                sorted(
                    artifact.model_dump_json(
                        exclude={"evidence": {"__all__": {"observed_at"}}}
                    )
                    for artifact in artifacts
                )
            ),
        )
        previous = self._publications_by_key.get(idempotency_key)
        if previous is not None:
            previous_fingerprint, snapshot_id = previous
            if previous_fingerprint != fingerprint:
                raise ValueError("idempotency key reused with different publication content")
            return snapshot_id

        snapshot_id = stable_id(
            subject, revision, *(sorted(artifact.id for artifact in artifacts))
        )
        self.publications.append(
            {
                "snapshot_id": snapshot_id,
                "subject": subject,
                "revision": revision,
                "artifacts": artifacts,
                "idempotency_key": idempotency_key,
            }
        )
        self._publications_by_key[idempotency_key] = (fingerprint, snapshot_id)
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
class DemoAdapters:
    knowledge: DemoKnowledge = field(default_factory=DemoKnowledge)
    alert_classifier: DemoAlertClassifier = field(default_factory=DemoAlertClassifier)
    reasoner: DemoReasoner = field(default_factory=DemoReasoner)
    extractor: DemoExtractor = field(default_factory=DemoExtractor)
    publisher: DemoPublisher = field(default_factory=DemoPublisher)
    notifier: DemoNotifier = field(default_factory=DemoNotifier)
    actions: DemoActions = field(default_factory=DemoActions)
