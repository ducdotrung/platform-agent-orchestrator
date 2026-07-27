"""Construct an observability backend without importing optional SDKs by default."""

from __future__ import annotations

from .base import ObservabilityBackend
from .noop import NoOpObservability
from .settings import ObservabilitySettings


def observability_from_env() -> ObservabilityBackend:
    return build_observability(ObservabilitySettings.from_env())


def build_observability(settings: ObservabilitySettings) -> ObservabilityBackend:
    if settings.backend == "none":
        return NoOpObservability()
    if settings.backend == "langfuse":
        try:
            from .langfuse_backend import LangfuseObservability
        except ImportError as exc:
            raise RuntimeError(
                "Langfuse support is not installed; run pip install -e '.[observability]'"
            ) from exc
        return LangfuseObservability(settings)
    raise ValueError(f"Unsupported observability backend: {settings.backend}")
