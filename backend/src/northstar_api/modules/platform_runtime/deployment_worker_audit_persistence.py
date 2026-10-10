"""Append-only deployment-machine audit events.

Each attempt is recorded as an intent followed by an outcome; an unresolved
intent is not a successful mutation. Database triggers additionally prohibit
UPDATE and DELETE in PostgreSQL (migration 0087).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class PlatformDeploymentWorkerAudit(Base):
    __tablename__ = "platform_deployment_worker_audit"
    __table_args__ = (
        UniqueConstraint("change_id", "sequence", name="uq_platform_worker_audit_change_sequence"),
        UniqueConstraint("attempt_id", "kind", name="uq_platform_worker_audit_attempt_kind"),
        Index("ix_platform_worker_audit_change_time", "change_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    change_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_changes.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    machine_subject: Mapped[str] = mapped_column(String(160), nullable=False)
    token_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    event_digest: Mapped[str] = mapped_column(String(64), nullable=False)
