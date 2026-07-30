from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from platform_agent_orchestrator.api import ReadinessReport, create_app
from platform_agent_orchestrator.settings import ApplicationSettings


@dataclass(frozen=True)
class StaticReadiness:
    ready: bool

    async def check(self) -> ReadinessReport:
        return ReadinessReport(
            ready=self.ready,
            checks={"sample_dependency": "ready" if self.ready else "unavailable"},
        )


def test_liveness_is_distinct_from_unready_admission() -> None:
    app = create_app(
        settings=ApplicationSettings(),
        readiness=StaticReadiness(ready=False),
    )

    with TestClient(app) as client:
        live = client.get("/livez")
        ready = client.get("/readyz")

    assert live.status_code == 200
    assert live.json() == {"status": "alive"}
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "checks": {"sample_dependency": "unavailable"},
    }


def test_demo_profile_is_unready_without_admission_authentication() -> None:
    with TestClient(create_app(settings=ApplicationSettings())) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"] == {
        "configuration": "ready",
        "authentication": "unconfigured",
        "demo_adapters": "ready",
        "replay_store": "process_local_demo",
        "persistence": "unavailable",
    }


def test_local_profile_is_not_ready_until_persistence_is_initialized() -> None:
    secret = "do-not-return"
    settings = ApplicationSettings.from_env(
        {
            "PLATFORM_PROFILE": "local",
            "PLATFORM_RUNTIME_ROLE": "api",
            "ORCHESTRATOR_DATABASE_URL": f"postgresql://sample:{secret}@db/app",
        }
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["persistence"] == "not_initialized"
    assert secret not in response.text


def test_request_size_limit_runs_before_routing_or_json_parsing() -> None:
    settings = ApplicationSettings(max_request_bytes=1_024)
    app = create_app(settings=settings)

    with TestClient(app) as client:
        response = client.post("/future-admission", content=b"x" * 1_025)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert "x" * 20 not in response.text


def test_http_and_unexpected_errors_are_bounded() -> None:
    app = create_app(settings=ApplicationSettings())

    @app.get("/validated")
    async def validated(limit: int) -> dict[str, int]:
        return {"limit": limit}

    @app.get("/test-error")
    async def test_error() -> None:
        raise RuntimeError("database password=do-not-return")

    with TestClient(app, raise_server_exceptions=False) as client:
        missing = client.get("/missing")
        invalid = client.get("/validated", params={"limit": "password=do-not-return"})
        failed = client.get("/test-error")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "http_404"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "request_validation_failed"
    assert "do-not-return" not in invalid.text
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "internal_error"
    assert "do-not-return" not in failed.text
    assert set(failed.json()["error"]) == {"code", "message", "request_id"}
