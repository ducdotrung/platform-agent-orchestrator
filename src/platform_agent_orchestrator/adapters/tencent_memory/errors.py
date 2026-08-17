"""Bounded TencentDB Agent Memory adapter errors."""

from __future__ import annotations

from platform_agent_orchestrator.ports.memory import MemoryPortError


class TencentMemoryError(MemoryPortError):
    """Base class for expected Tencent memory provider failures."""


class TencentMemoryConfigurationError(TencentMemoryError):
    """Tencent memory configuration is missing or unsafe."""


class TencentMemoryTimeoutError(TencentMemoryError, TimeoutError):
    """Tencent memory request exceeded the configured timeout."""


class TencentMemoryNetworkError(TencentMemoryError, ConnectionError):
    """Tencent memory request failed before receiving a response."""


class TencentMemoryInvalidResponseError(TencentMemoryError):
    """Tencent memory returned a response that violates its wire contract."""


class TencentMemoryServiceError(TencentMemoryError):
    """Tencent memory rejected a valid HTTP request."""

    def __init__(
        self,
        *,
        status_code: int,
        code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        details = [f"status={status_code}"]
        if code is not None:
            details.append(f"code={code}")
        if request_id:
            details.append(f"request_id={request_id}")
        super().__init__("Tencent memory service error (" + ", ".join(details) + ")")


class TencentMemoryIdempotencyConflictError(TencentMemoryError):
    """An idempotency key was reused for different framework memory content."""


class TencentMemoryIdempotencyUnavailableError(TencentMemoryError):
    """The remote idempotency scan could not safely prove a write is new."""
