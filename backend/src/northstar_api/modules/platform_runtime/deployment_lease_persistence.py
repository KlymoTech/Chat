"""Deployment worker lease table (migration 0085).

Keep the execution claim separate from historical execution reports.
Leases never attest that a provider mutation has succeeded.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class PlatformDeploymentLease(Base):
    __tablename__ = "platform_deployment_leases"
    __table_args__ = (
        Index("ix_platform_deployment_leases_status_expires", "status", "lease_expires_at"),
    )

    change_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_changes.id", ondelete="RESTRICT"), primary_key=True
    )
    environment: Mapped[str] = mapped_column(String(32))
    source_digest: Mapped[str] = mapped_column(String(64))
    target_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="ready")
    lease_token: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
