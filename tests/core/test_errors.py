from platform_agent_orchestrator.core import (
    DuplicateRegistrationError,
    FlowCompatibilityError,
    MissingCapabilityError,
)


def test_registration_errors_preserve_machine_readable_details() -> None:
    duplicate = DuplicateRegistrationError("flow", "engineering-assistance")
    missing = MissingCapabilityError("knowledge.search")

    assert (duplicate.kind, duplicate.name) == ("flow", "engineering-assistance")
    assert missing.capability == "knowledge.search"


def test_flow_compatibility_error_sorts_missing_capabilities() -> None:
    error = FlowCompatibilityError(
        flow="engineering-assistance",
        missing_capabilities={"memory.recall", "knowledge.search"},
    )

    assert error.missing_capabilities == ("knowledge.search", "memory.recall")
