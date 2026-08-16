"""Translate framework pauses to and from LangGraph interrupts."""

from __future__ import annotations

from typing import Any

from langgraph.types import Command, interrupt

from platform_agent_orchestrator.sdk.nodes import PauseRequest

INTERRUPT_RESULT_KEY = "__interrupt__"


def pause_execution(request: PauseRequest, updates: dict[str, Any]) -> Any:
    """Pause natively and return the resume value when execution continues."""

    return interrupt(
        {
            "request": request.model_dump(mode="json"),
            "updates": updates,
        }
    )


def resume_command(payload: dict[str, Any]) -> object:
    """Create an implementation-native resume command behind an object boundary."""

    return Command(resume=payload)


def extract_pause(result: dict[str, Any]) -> tuple[PauseRequest | None, dict[str, Any]]:
    """Extract the first framework pause and prospective updates from a result."""

    interrupts = result.get(INTERRUPT_RESULT_KEY)
    if not isinstance(interrupts, (list, tuple)) or not interrupts:
        return None, {}
    value = getattr(interrupts[0], "value", None)
    if not isinstance(value, dict):
        return None, {}
    request = value.get("request")
    updates = value.get("updates")
    if not isinstance(request, dict):
        return None, {}
    return (
        PauseRequest.model_validate(request),
        dict(updates) if isinstance(updates, dict) else {},
    )
