from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from platform_agent_orchestrator.adapters import DemoPlatformServices
from platform_agent_orchestrator.contracts import DomainEvent, EventType
from platform_agent_orchestrator.registry import WorkflowRegistry


def event(event_type: EventType, subject: str, payload: dict) -> DomainEvent:
    return DomainEvent.from_legacy(
        type=event_type,
        source="test",
        subject=subject,
        idempotency_key=f"test:{subject}",
        payload=payload,
    )


def test_alert_suppresses_bounded_known_noise_without_reasoning() -> None:
    demo = DemoPlatformServices()
    registry = WorkflowRegistry(demo.as_services())
    alert = event(
        EventType.ALERT_RECEIVED,
        "CLIENT-1",
        {"title": "Client disconnected", "count": 4, "severity": "warning"},
    )

    result = registry.invoke("alert", alert)

    assert result["status"] == "suppressed"
    assert not demo.notifier.messages


def test_alert_enriches_and_notifies_actionable_incident() -> None:
    demo = DemoPlatformServices()
    registry = WorkflowRegistry(demo.as_services())
    alert = event(
        EventType.ALERT_RECEIVED,
        "PAYMENT-1",
        {
            "title": "Payment timeout",
            "service": "order-service",
            "count": 200,
            "users": 25,
            "severity": "critical",
        },
    )

    result = registry.invoke("alert", alert)

    assert result["status"] == "notified"
    assert result["alert"]["priority"] == "P0"
    assert result["decision"]["evidence_ids"]
    assert len(demo.notifier.messages) == 1


def test_refresh_extracts_three_surfaces_and_publishes_one_snapshot() -> None:
    demo = DemoPlatformServices()
    registry = WorkflowRegistry(demo.as_services())
    refresh = event(
        EventType.PR_MERGED,
        "payment-service",
        {
            "revision": "abc123",
            "changed_files": ["src/app.py", "helm/values.yaml", "docs/contract.md"],
        },
    )

    result = registry.invoke("refresh", refresh)

    assert result["status"] == "published"
    assert {item["artifact_type"] for item in result["artifacts"]} == {
        "code",
        "config",
        "document",
    }
    assert not result["validation_errors"]
    assert len(demo.publisher.publications) == 1


def test_engineering_question_routes_to_qa_and_verifies_evidence() -> None:
    demo = DemoPlatformServices()
    registry = WorkflowRegistry(demo.as_services())
    question = event(
        EventType.ENGINEERING_QUESTION,
        "question-1",
        {"question": "What regression test coverage is needed?", "role": "auto"},
    )

    result = registry.invoke("engineering", question)

    assert result["role"] == "qa"
    assert result["status"] == "answered"
    assert result["evidence_verified"] is True


def test_safe_sre_action_executes_without_interrupt() -> None:
    demo = DemoPlatformServices()
    registry = WorkflowRegistry(demo.as_services())
    ticket = event(
        EventType.SRE_TICKET_UPDATED,
        "INF-1",
        {
            "key": "INF-1",
            "summary": "Inspect service",
            "service": "payment-service",
            "operation": "inspect",
        },
    )

    result = registry.invoke("sre", ticket)

    assert result["risk"] == "safe"
    assert result["status"] == "completed"
    assert result["verified"] is True


def test_risky_sre_action_pauses_and_resumes_with_approval() -> None:
    demo = DemoPlatformServices()
    checkpointer = InMemorySaver()
    registry = WorkflowRegistry(demo.as_services(), checkpointer=checkpointer)
    graph = registry.build("sre")
    ticket = event(
        EventType.SRE_TICKET_UPDATED,
        "INF-2",
        {
            "key": "INF-2",
            "summary": "Restart production service",
            "service": "payment-service",
            "environment": "prod",
            "operation": "restart",
        },
    )
    config = {"configurable": {"thread_id": "INF-2"}}

    paused = graph.invoke({"event": ticket.model_dump(mode="json")}, config=config)

    assert paused["risk"] == "risky"
    assert "__interrupt__" in paused
    assert not demo.actions.results

    resumed = graph.invoke(
        Command(resume={"approved": True, "actor": "on-call", "reason": "Incident mitigation"}),
        config=config,
    )

    assert resumed["approval"]["approved"] is True
    assert resumed["status"] == "completed"
    assert len(demo.actions.results) == 1


def test_registry_rejects_wrong_event_type() -> None:
    demo = DemoPlatformServices()
    registry = WorkflowRegistry(demo.as_services())
    wrong = event(EventType.ENGINEERING_QUESTION, "q", {"question": "hello"})

    try:
        registry.invoke("alert", wrong)
    except ValueError as exc:
        assert "expects" in str(exc)
    else:
        raise AssertionError("expected registry to reject a mismatched event")
