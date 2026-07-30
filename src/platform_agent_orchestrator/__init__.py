"""Platform agent orchestration reference implementation."""

from .contracts import (
    AlertReceivedPayloadV1,
    DomainEvent,
    EventEnvelopeV1,
    EventType,
    EvidenceRef,
    KnowledgeArtifact,
)

__all__ = [
    "AlertReceivedPayloadV1",
    "DomainEvent",
    "EventEnvelopeV1",
    "EventType",
    "EvidenceRef",
    "KnowledgeArtifact",
]
__version__ = "0.1.0"
