"""SQLAlchemy mappings for the frozen initial application schema."""

from __future__ import annotations

from sqlalchemy.orm import registry

from .schema_0001 import build_metadata

_mapper_registry = registry(metadata=build_metadata())
Base = _mapper_registry.generate_base()


class EventRecord(Base):
    __table__ = Base.metadata.tables["orchestrator.events"]


class RunRecord(Base):
    __table__ = Base.metadata.tables["orchestrator.runs"]


class DeliveryJobRecord(Base):
    __table__ = Base.metadata.tables["orchestrator.delivery_jobs"]


class DeliveryAttemptRecord(Base):
    __table__ = Base.metadata.tables["orchestrator.delivery_attempts"]


class IdempotencyClaimRecord(Base):
    __table__ = Base.metadata.tables["orchestrator.idempotency_claims"]


class AuthReplayClaimRecord(Base):
    __table__ = Base.metadata.tables["orchestrator.auth_replay_claims"]


class ApprovalRecord(Base):
    __table__ = Base.metadata.tables["orchestrator.approvals"]


class SideEffectRecord(Base):
    __table__ = Base.metadata.tables["orchestrator.side_effects"]


class AuditEventRecord(Base):
    __table__ = Base.metadata.tables["orchestrator.audit_events"]
