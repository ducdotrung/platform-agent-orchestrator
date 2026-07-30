"""FastAPI process boundary for health and future admission routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import Protocol
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from platform_agent_orchestrator.bootstrap import RuntimeDependencies, build_dependencies
from platform_agent_orchestrator.settings import (
    ApplicationSettings,
    DeploymentProfile,
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

    async def check(self) -> ReadinessReport:
        if self.settings.profile == DeploymentProfile.DEMO:
            return ReadinessReport(
                ready=True,
                checks={"configuration": "ready", "demo_adapters": "ready"},
            )
        return ReadinessReport(
            ready=False,
            checks={"configuration": "ready", "persistence": "not_initialized"},
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


def create_app(
    *,
    settings: ApplicationSettings | None = None,
    dependencies: RuntimeDependencies | None = None,
    readiness: ReadinessProbe | None = None,
) -> FastAPI:
    if settings is not None and dependencies is not None:
        raise ValueError("pass settings or dependencies, not both")
    application_settings = settings or (
        dependencies.settings if dependencies is not None else ApplicationSettings.from_env()
    )
    readiness_probe = readiness or ConfigurationReadinessProbe(application_settings)
    owned_dependencies: RuntimeDependencies | None = None

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

    app = FastAPI(
        title="Platform Agent Orchestrator",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=application_settings.max_request_bytes)

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

    @app.get("/livez")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/readyz")
    async def ready() -> JSONResponse:
        report = await readiness_probe.check()
        return JSONResponse(
            status_code=200 if report.ready else 503,
            content={
                "status": "ready" if report.ready else "not_ready",
                "checks": report.checks,
            },
        )

    return app


app = create_app()
