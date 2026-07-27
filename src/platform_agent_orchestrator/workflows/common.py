"""Shared helpers kept small enough to avoid coupling domain workflows."""

from __future__ import annotations

from typing import Any

from platform_agent_orchestrator.contracts import DomainEvent, EvidenceRef


def load_event(state: dict[str, Any]) -> DomainEvent:
    return DomainEvent.model_validate(state["event"])


def dump_evidence(items: list[EvidenceRef]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]


def load_evidence(items: list[dict[str, Any]]) -> list[EvidenceRef]:
    return [EvidenceRef.model_validate(item) for item in items]
