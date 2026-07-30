"""Run local examples without credentials or external services."""

from __future__ import annotations

import argparse
import json
from typing import Any

from platform_agent_orchestrator.adapters import DemoPlatformServices
from platform_agent_orchestrator.contracts import (
    AlertReceivedPayloadV1,
    DomainEvent,
    EventEnvelopeV1,
    EventType,
)
from platform_agent_orchestrator.observability import observability_from_env
from platform_agent_orchestrator.registry import WorkflowRegistry


def sample_events() -> dict[str, DomainEvent]:
    return {
        "alert": EventEnvelopeV1(
            source="sentry",
            subject="PAYMENT-502",
            idempotency_key="sentry:PAYMENT-502:2026-07-27T10",
            payload=AlertReceivedPayloadV1(
                alert_id="PAYMENT-502",
                title="Payment dependency timeout",
                service="order-service",
                severity="critical",
                count=240,
                users=72,
                environment="prod",
            ),
        ).to_domain_event(),
        "refresh": DomainEvent.from_legacy(
            type=EventType.PR_MERGED,
            source="bitbucket",
            subject="payment-service",
            idempotency_key="bitbucket:payment-service:abc123",
            payload={
                "revision": "abc123",
                "changed_files": [
                    "src/payment/client.py",
                    "helm/payment/values-prod.yaml",
                    "docs/payment-contract.md",
                ],
            },
        ),
        "sre": DomainEvent.from_legacy(
            type=EventType.SRE_TICKET_UPDATED,
            source="jira",
            subject="INF-1001",
            idempotency_key="jira:INF-1001:3",
            payload={
                "key": "INF-1001",
                "summary": "Inspect payment-service health",
                "service": "payment-service",
                "environment": "prod",
                "operation": "inspect",
            },
        ),
        "engineering": DomainEvent.from_legacy(
            type=EventType.ENGINEERING_QUESTION,
            source="code-atlas",
            subject="question-1",
            idempotency_key="code-atlas:question-1",
            payload={
                "question": "Which regression tests cover a payment timeout change?",
                "role": "auto",
            },
        ),
    }


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    hidden = {"event", "evidence", "artifacts"}
    return {key: value for key, value in result.items() if key not in hidden}


def run_demo(selection: str) -> int:
    demo = DemoPlatformServices()
    observability = observability_from_env()
    registry = WorkflowRegistry(demo.as_services(), observability=observability)
    try:
        events = sample_events()
        names = list(events) if selection == "all" else [selection]
        for name in names:
            result = registry.invoke(name, events[name])
            print(f"\n=== {name} ===")
            print(json.dumps(compact_result(result), indent=2, default=str))
        return 0
    finally:
        # Short-lived processes must flush buffered telemetry before exiting.
        observability.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo", help="run deterministic workflow demos")
    demo.add_argument("workflow", choices=["alert", "refresh", "sre", "engineering", "all"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        return run_demo(args.workflow)
    return 2
