"""Generic workflow runtime contracts and concrete runtime adapters."""

from __future__ import annotations

from .engine import WorkflowRuntime
from .execution import RunResult, RunStatus

__all__ = [
    "RunResult",
    "RunStatus",
    "WorkflowRuntime",
    "checkpoint_migrate_main",
    "worker_main",
]

_LEGACY_EXPORTS = {
    "DatabaseReadinessProbe",
    "WORKER_READY_PATH",
    "_runtime_settings",
    "build_api_app",
    "checkpoint_migrate_main",
    "run_worker",
    "worker_main",
}


def __getattr__(name: str) -> object:
    """Load legacy process composition only for callers that still request it."""

    if name in _LEGACY_EXPORTS:
        from . import legacy

        return getattr(legacy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
