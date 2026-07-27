"""Environment-driven observability configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


def _boolean(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


@dataclass(frozen=True)
class ObservabilitySettings:
    backend: str = "none"
    public_key: str | None = None
    secret_key: str | None = None
    base_url: str | None = None
    environment: str = "development"
    release: str | None = None
    sample_rate: float = 1.0
    capture_content: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ObservabilitySettings:
        values = os.environ if environ is None else environ
        backend = values.get("PLATFORM_OBSERVABILITY", "none").strip().lower()
        if backend not in {"none", "langfuse"}:
            raise ValueError("PLATFORM_OBSERVABILITY must be 'none' or 'langfuse'")
        try:
            sample_rate = float(values.get("LANGFUSE_SAMPLE_RATE", "1.0"))
        except ValueError as exc:
            raise ValueError("LANGFUSE_SAMPLE_RATE must be a number from 0 to 1") from exc
        if not 0.0 <= sample_rate <= 1.0:
            raise ValueError("LANGFUSE_SAMPLE_RATE must be between 0 and 1")
        return cls(
            backend=backend,
            public_key=values.get("LANGFUSE_PUBLIC_KEY") or None,
            secret_key=values.get("LANGFUSE_SECRET_KEY") or None,
            base_url=values.get("LANGFUSE_BASE_URL") or None,
            environment=values.get("LANGFUSE_TRACING_ENVIRONMENT", "development"),
            release=values.get("LANGFUSE_RELEASE") or None,
            sample_rate=sample_rate,
            capture_content=_boolean(values.get("PLATFORM_TRACE_CAPTURE_CONTENT"), default=False),
        )
