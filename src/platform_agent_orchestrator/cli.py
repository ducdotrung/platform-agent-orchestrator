"""Run local examples without credentials or external services."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from platform_agent_orchestrator.bootstrap import build_dependencies
from platform_agent_orchestrator.contracts import (
    DomainEvent,
    EventType,
)
from platform_agent_orchestrator.core import DomainEvent as V2DomainEvent


def sample_events() -> dict[str, DomainEvent | V2DomainEvent]:
    return {
        "alert": V2DomainEvent(
            id="demo-alert-1",
            type="monitoring.alert.received",
            source="sentry",
            subject="PAYMENT-502",
            occurred_at=datetime.now(UTC),
            correlation_id="demo-alert-correlation-1",
            idempotency_key="sentry:PAYMENT-502:2026-07-27T10",
            data={
                "alert_id": "PAYMENT-502",
                "title": "Payment dependency timeout",
                "service": "order-service",
                "severity": "critical",
                "count": 240,
                "users": 72,
                "environment": "prod",
            },
        ),
        "refresh": V2DomainEvent(
            id="demo-refresh-1",
            type="scm.pull_request.merged",
            source="bitbucket",
            subject="payment-service",
            occurred_at=datetime.now(UTC),
            correlation_id="demo-refresh-correlation-1",
            idempotency_key="bitbucket:payment-service:abc123",
            data={
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
        "engineering": V2DomainEvent(
            id=str(uuid4()),
            type="engineering.question.received",
            source="code-atlas",
            subject="question-1",
            occurred_at=datetime.now(UTC),
            correlation_id=str(uuid4()),
            idempotency_key="code-atlas:question-1",
            data={
                "question": "Which regression tests cover a payment timeout change?",
                "role": "auto",
            },
        ),
    }


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    hidden = {"event", "evidence", "memories", "artifacts"}
    return {key: value for key, value in result.items() if key not in hidden}


def run_demo(selection: str) -> int:
    dependencies = build_dependencies()
    registry = dependencies.registry()
    try:
        events = sample_events()
        names = list(events) if selection == "all" else [selection]
        for name in names:
            if name in {"alert", "engineering", "refresh"}:
                migrated_event = events[name]
                if not isinstance(migrated_event, V2DomainEvent):
                    raise TypeError(f"{name} demo requires a v2 domain event")
                dispatched = asyncio.run(
                    dependencies.dispatcher().dispatch(migrated_event)
                )
                if len(dispatched) != 1:
                    raise RuntimeError(f"{name} demo must resolve exactly one flow")
                result = dispatched[0].output
            else:
                legacy_event = events[name]
                if not isinstance(legacy_event, DomainEvent):
                    raise TypeError("legacy demo requires a legacy domain event")
                result = registry.invoke(name, legacy_event)
            print(f"\n=== {name} ===")
            print(json.dumps(compact_result(result), indent=2, default=str))
        return 0
    finally:
        # Short-lived processes must flush buffered telemetry before exiting.
        dependencies.shutdown()


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
