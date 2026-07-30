"""Platform agent orchestration reference implementation."""

from .contracts import (
    AlertReceivedPayloadV1,
    DomainEvent,
    EventEnvelopeV1,
    EventType,
    EvidenceRef,
    KnowledgeArtifact,
)
from .service_contracts import (
    ApprovalContractV1,
    DeliveryContractV1,
    ErrorContractV1,
    FeedbackContractV1,
    RetryContractV1,
    RunContractV1,
)

__all__ = [
    "AlertReceivedPayloadV1",
    "ApprovalContractV1",
    "DeliveryContractV1",
    "DomainEvent",
    "ErrorContractV1",
    "EventEnvelopeV1",
    "EventType",
    "EvidenceRef",
    "FeedbackContractV1",
    "KnowledgeArtifact",
    "RetryContractV1",
    "RunContractV1",
]
__version__ = "0.1.0"
