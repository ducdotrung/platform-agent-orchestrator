"""Bounded operational metrics and public-safe structured event logs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

_LOG_FIELDS = frozenset(
    {
        "action",
        "decision",
        "dependency",
        "event",
        "method",
        "outcome",
        "route",
        "status",
        "workflow",
    }
)
_SENSITIVE_FRAGMENTS = ("authorization", "cookie", "password", "secret", "token")


@dataclass
class ServiceMetrics:
    registry: CollectorRegistry = field(default_factory=CollectorRegistry)

    def __post_init__(self) -> None:
        self.http_requests = Counter(
            "orchestrator_http_requests_total",
            "Bounded HTTP request outcomes.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.delivery_claims = Counter(
            "orchestrator_delivery_claims_total",
            "Delivery claim outcomes.",
            ("outcome",),
            registry=self.registry,
        )
        self.worker_outcomes = Counter(
            "orchestrator_worker_outcomes_total",
            "Worker execution outcomes.",
            ("outcome",),
            registry=self.registry,
        )
        self.run_transitions = Counter(
            "orchestrator_run_transitions_total",
            "Durable run transitions.",
            ("status",),
            registry=self.registry,
        )
        self.approval_decisions = Counter(
            "orchestrator_approval_decisions_total",
            "Durable approval decisions.",
            ("decision",),
            registry=self.registry,
        )
        self.feedback_records = Counter(
            "orchestrator_feedback_records_total",
            "Durable feedback records.",
            ("rating",),
            registry=self.registry,
        )
        self.side_effect_outcomes = Counter(
            "orchestrator_side_effect_outcomes_total",
            "Durable side-effect outcomes.",
            ("outcome",),
            registry=self.registry,
        )
        self.dependency_ready = Gauge(
            "orchestrator_dependency_ready",
            "Dependency readiness (1 ready, 0 unavailable).",
            ("dependency",),
            registry=self.registry,
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


@dataclass(frozen=True)
class PublicEventLogger:
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("platform_agent_orchestrator.events")
    )

    def info(self, event: str, **fields: str | int | bool) -> None:
        payload = _public_log_payload(event, fields)
        self.logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _public_log_payload(
    event: str,
    fields: dict[str, str | int | bool],
) -> dict[str, Any]:
    if not event or len(event) > 64:
        raise ValueError("log event must contain 1 to 64 characters")
    payload: dict[str, Any] = {"event": event}
    for key, value in fields.items():
        normalized = key.lower().replace("-", "_")
        if normalized not in _LOG_FIELDS or any(
            part in normalized for part in _SENSITIVE_FRAGMENTS
        ):
            raise ValueError(f"log field is not public-safe: {key}")
        if isinstance(value, str) and len(value) > 128:
            raise ValueError(f"log field exceeds 128 characters: {key}")
        payload[normalized] = value
    return payload


def bounded_route(path: str) -> str:
    if path in {"/livez", "/readyz", "/metrics", "/v1/events", "/v1/approvals"}:
        return path
    parts = path.strip("/").split("/")
    if len(parts) == 3 and parts[:2] == ["v1", "runs"]:
        return "/v1/runs/{run_id}"
    if len(parts) == 4 and parts[:2] == ["v1", "runs"] and parts[3] in {
        "approvals",
        "feedback",
    }:
        return f"/v1/runs/{{run_id}}/{parts[3]}"
    return "other"
