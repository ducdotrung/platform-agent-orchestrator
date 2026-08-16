"""Runtime-owned execution context supplied to extension code."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionIdentity:
    """Stable identifiers that may safely cross execution boundaries."""

    run_id: str
    thread_id: str
    correlation_id: str
    tenant_id: str | None = None


@dataclass
class ExecutionContext:
    """Runtime services available to nodes, agents, and providers.

    The concrete registry, policy, and observability types are intentionally
    represented as framework service objects here. Core must not import the
    implementation layers that provide them.
    """

    identity: ExecutionIdentity
    capabilities: object
    agents: object
    policy: object
    observability: object
    metadata: Mapping[str, Any]
