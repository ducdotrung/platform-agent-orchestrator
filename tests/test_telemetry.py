from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from platform_agent_orchestrator.api import (
    ReadinessReport,
    create_app,
)
from platform_agent_orchestrator.settings import ApplicationSettings
from platform_agent_orchestrator.telemetry import PublicEventLogger, ServiceMetrics


class ReadyProbe:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(
            ready=True,
            checks={
                "configuration": "ready",
                "persistence": "ready",
                "replay_store": "ready",
            },
        )


def test_metrics_use_bounded_routes_and_publish_dependency_state() -> None:
    metrics = ServiceMetrics()
    app = create_app(
        settings=ApplicationSettings(),
        readiness=ReadyProbe(),
        service_metrics=metrics,
    )
    run_id = "secret-run-123"

    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 200
        assert client.get(f"/v1/runs/{run_id}").status_code == 503
        response = client.get("/metrics")

    body = response.text
    assert response.status_code == 200
    assert 'route="/v1/runs/{run_id}"' in body
    assert run_id not in body
    assert 'dependency="persistence"} 1.0' in body
    assert "orchestrator_http_requests_total" in body


def test_all_business_metric_dimensions_are_bounded_outcomes() -> None:
    metrics = ServiceMetrics()
    metrics.delivery_claims.labels("claimed").inc()
    metrics.worker_outcomes.labels("succeeded").inc()
    metrics.run_transitions.labels("waiting_approval").inc()
    metrics.approval_decisions.labels("approved").inc()
    metrics.feedback_records.labels("helpful").inc()
    metrics.side_effect_outcomes.labels("succeeded").inc()

    body = metrics.render().decode()
    for expected in (
        'outcome="claimed"',
        'outcome="succeeded"',
        'status="waiting_approval"',
        'decision="approved"',
        'rating="helpful"',
    ):
        assert expected in body


def test_public_event_logs_reject_sensitive_or_unbounded_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.public_event_logger")
    logger.disabled = False
    logger.propagate = True
    event_logger = PublicEventLogger(logger)
    with caplog.at_level(logging.INFO, logger=logger.name):
        event_logger.info("worker_outcome", outcome="succeeded", workflow="alert")

    assert '"outcome":"succeeded"' in caplog.text
    with pytest.raises(ValueError):
        event_logger.info("unsafe", token="do-not-log")
    with pytest.raises(ValueError):
        event_logger.info("unsafe", outcome="x" * 129)
