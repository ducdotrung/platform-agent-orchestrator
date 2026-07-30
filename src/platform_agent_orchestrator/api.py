"""FastAPI process boundary for health and future admission routes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, Protocol
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from platform_agent_orchestrator.bootstrap import RuntimeDependencies, build_dependencies
from platform_agent_orchestrator.contracts import EventEnvelopeV1
from platform_agent_orchestrator.persistence import (
    ApprovalConflict,
    ApprovalExpired,
    ApprovalNotFound,
    ApprovalStale,
    EventRepository,
    FeedbackRunNotFound,
    IdempotencyConflict,
)
from platform_agent_orchestrator.security import (
    AdmissionSecurity,
    AdmissionSecurityError,
    AuthorizationContext,
    ReviewerAuthorizationContext,
    ReviewerSecurity,
    require_admission_authorization,
    require_reviewer_authorization,
    require_run_read_authorization,
)
from platform_agent_orchestrator.service_contracts import (
    ApprovalDecisionRequestV1,
    FeedbackRequestV1,
)
from platform_agent_orchestrator.settings import (
    ApplicationSettings,
    DeploymentProfile,
)
from platform_agent_orchestrator.telemetry import (
    PublicEventLogger,
    ServiceMetrics,
    bounded_route,
)


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    checks: dict[str, str]


class ReadinessProbe(Protocol):
    async def check(self) -> ReadinessReport: ...


@dataclass(frozen=True)
class ConfigurationReadinessProbe:
    settings: ApplicationSettings
    persistence_ready: bool = False
    replay_ready: bool = False

    async def check(self) -> ReadinessReport:
        authentication = (
            "ready" if self.settings.webhook_signing_secret is not None else "unconfigured"
        )
        if self.settings.profile == DeploymentProfile.DEMO:
            return ReadinessReport(
                ready=authentication == "ready" and self.persistence_ready,
                checks={
                    "configuration": "ready",
                    "authentication": authentication,
                    "demo_adapters": "ready",
                    "replay_store": "process_local_demo",
                    "persistence": "ready" if self.persistence_ready else "unavailable",
                },
            )
        ready = (
            authentication == "ready"
            and self.persistence_ready
            and self.replay_ready
        )
        return ReadinessReport(
            ready=ready,
            checks={
                "configuration": "ready",
                "authentication": authentication,
                "persistence": "ready" if self.persistence_ready else "not_initialized",
                "replay_store": "ready" if self.replay_ready else "not_initialized",
            },
        )


def _public_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": str(uuid4()),
            }
        },
    )


class RequestSizeLimitMiddleware:
    """Buffer bounded mutation bodies before parsers or route handlers run."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError:
                await _public_error(400, "invalid_content_length", "Invalid Content-Length")(
                    scope, receive, send
                )
                return
            if content_length < 0:
                await _public_error(400, "invalid_content_length", "Invalid Content-Length")(
                    scope, receive, send
                )
                return
            if content_length > self.max_bytes:
                await _public_error(413, "request_too_large", "Request body exceeds limit")(
                    scope, receive, send
                )
                return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            body.extend(chunk)
            if len(body) > self.max_bytes:
                await _public_error(413, "request_too_large", "Request body exceeds limit")(
                    scope, receive, send
                )
                return
            more_body = bool(message.get("more_body", False))

        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)


class OperationalTelemetryMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        metrics: ServiceMetrics,
        event_logger: PublicEventLogger,
    ) -> None:
        self.app = app
        self.metrics = metrics
        self.event_logger = event_logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status_code = 500

        async def observe_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, observe_send)
        finally:
            method = str(scope.get("method", "UNKNOWN"))
            route = bounded_route(str(scope.get("path", "")))
            status = str(status_code)
            try:
                self.metrics.http_requests.labels(method, route, status).inc()
                self.event_logger.info(
                    "http_request",
                    method=method,
                    route=route,
                    status=status,
                )
            except Exception:
                pass


def create_app(
    *,
    settings: ApplicationSettings | None = None,
    dependencies: RuntimeDependencies | None = None,
    readiness: ReadinessProbe | None = None,
    admission_security: AdmissionSecurity | None = None,
    reviewer_security: ReviewerSecurity | None = None,
    event_repository: EventRepository | None = None,
    service_metrics: ServiceMetrics | None = None,
    public_event_logger: PublicEventLogger | None = None,
    async_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    if settings is not None and dependencies is not None:
        raise ValueError("pass settings or dependencies, not both")
    application_settings = settings or (
        dependencies.settings if dependencies is not None else ApplicationSettings.from_env()
    )
    readiness_probe = readiness or ConfigurationReadinessProbe(
        application_settings,
        persistence_ready=event_repository is not None,
        replay_ready=admission_security is not None,
    )
    owned_dependencies: RuntimeDependencies | None = None
    metrics = service_metrics or ServiceMetrics()
    event_logger = public_event_logger or PublicEventLogger()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal owned_dependencies
        runtime = dependencies
        if runtime is None:
            owned_dependencies = build_dependencies(application_settings)
            runtime = owned_dependencies
        app.state.dependencies = runtime
        try:
            yield
        finally:
            if owned_dependencies is not None:
                owned_dependencies.shutdown()
            if async_shutdown is not None:
                await async_shutdown()

    app = FastAPI(
        title="Platform Agent Orchestrator",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=application_settings.max_request_bytes)
    app.add_middleware(
        OperationalTelemetryMiddleware,
        metrics=metrics,
        event_logger=event_logger,
    )
    app.state.admission_security = admission_security or AdmissionSecurity.from_settings(
        application_settings
    )
    app.state.reviewer_security = reviewer_security or ReviewerSecurity.from_settings(
        application_settings
    )
    app.state.event_repository = event_repository
    app.state.service_metrics = metrics

    @app.exception_handler(AdmissionSecurityError)
    async def admission_security_error(
        _request: Request, error: AdmissionSecurityError
    ) -> JSONResponse:
        return _public_error(error.status_code, error.code, error.public_message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return _public_error(422, "request_validation_failed", "Request validation failed")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        try:
            phrase = HTTPStatus(error.status_code).phrase
        except ValueError:
            phrase = "Request failed"
        return _public_error(error.status_code, f"http_{error.status_code}", phrase)

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception) -> JSONResponse:
        return _public_error(500, "internal_error", "Internal server error")

    @app.post("/v1/events")
    async def admit_event(
        envelope: EventEnvelopeV1,
        authorization: Annotated[
            AuthorizationContext,
            Depends(require_admission_authorization),
        ],
    ) -> JSONResponse:
        repository: EventRepository | None = app.state.event_repository
        if repository is None:
            return _public_error(503, "persistence_unavailable", "Persistence is unavailable")
        try:
            result = await repository.admit_event(envelope, authorization)
        except IdempotencyConflict:
            return _public_error(
                409,
                "idempotency_conflict",
                "Idempotency key conflicts with an accepted event",
            )
        return JSONResponse(
            status_code=200 if result.duplicate else 202,
            content={
                "schema_version": "1",
                "run_id": result.run_id,
                "status": result.status.value,
                "duplicate": result.duplicate,
            },
        )

    @app.get("/v1/runs/{run_id}")
    async def get_run(
        run_id: str,
        authorization: Annotated[
            AuthorizationContext,
            Depends(require_run_read_authorization),
        ],
    ) -> JSONResponse:
        repository: EventRepository | None = app.state.event_repository
        if repository is None:
            return _public_error(503, "persistence_unavailable", "Persistence is unavailable")
        run = await repository.get_run(run_id, authorization.scope_id)
        if run is None:
            return _public_error(404, "run_not_found", "Run not found")
        return JSONResponse(status_code=200, content=run.public_dump())

    @app.get("/v1/approvals")
    async def list_approvals(
        authorization: Annotated[
            ReviewerAuthorizationContext,
            Depends(require_reviewer_authorization),
        ],
    ) -> JSONResponse:
        repository: EventRepository | None = app.state.event_repository
        if repository is None:
            return _public_error(503, "persistence_unavailable", "Persistence is unavailable")
        approvals = await repository.list_pending_approvals(authorization.scope_id)
        return JSONResponse(
            status_code=200,
            content={
                "schema_version": "1",
                "items": [approval.public_dump() for approval in approvals],
            },
        )

    @app.post("/v1/runs/{run_id}/approvals")
    async def decide_approval(
        run_id: str,
        decision: ApprovalDecisionRequestV1,
        authorization: Annotated[
            ReviewerAuthorizationContext,
            Depends(require_reviewer_authorization),
        ],
    ) -> JSONResponse:
        repository: EventRepository | None = app.state.event_repository
        if repository is None:
            return _public_error(503, "persistence_unavailable", "Persistence is unavailable")
        try:
            approval = await repository.decide_approval(run_id, decision, authorization)
        except ApprovalNotFound:
            return _public_error(404, "approval_not_found", "Approval was not found")
        except ApprovalExpired:
            return _public_error(410, "approval_expired", "Approval has expired")
        except ApprovalStale:
            return _public_error(409, "approval_stale", "Approval state has changed")
        except ApprovalConflict:
            return _public_error(409, "approval_conflict", "Approval decision conflicts")
        return JSONResponse(status_code=202, content=approval.public_dump())

    @app.post("/v1/runs/{run_id}/feedback")
    async def create_feedback(
        run_id: str,
        feedback_request: FeedbackRequestV1,
        authorization: Annotated[
            ReviewerAuthorizationContext,
            Depends(require_reviewer_authorization),
        ],
    ) -> JSONResponse:
        repository: EventRepository | None = app.state.event_repository
        if repository is None:
            return _public_error(503, "persistence_unavailable", "Persistence is unavailable")
        try:
            feedback = await repository.ingest_feedback(
                run_id, feedback_request, authorization
            )
        except FeedbackRunNotFound:
            return _public_error(404, "feedback_run_not_found", "Run was not found")
        if feedback.trace_id:
            try:
                app.state.dependencies.observability.score(
                    feedback.trace_id,
                    "feedback.rating",
                    feedback.rating.value,
                    data_type="CATEGORICAL",
                )
            except Exception:
                pass
        return JSONResponse(status_code=201, content=feedback.public_dump())

    @app.get("/livez")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/readyz")
    async def ready() -> JSONResponse:
        report = await readiness_probe.check()
        for dependency, state in report.checks.items():
            metrics.dependency_ready.labels(dependency).set(1 if state == "ready" else 0)
        return JSONResponse(
            status_code=200 if report.ready else 503,
            content={
                "status": "ready" if report.ready else "not_ready",
                "checks": report.checks,
            },
        )

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        return Response(
            content=metrics.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app


app = create_app()
