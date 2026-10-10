"""Immutable per-step deployment checkpoints, never an AWS mutation trigger."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class PlatformDeploymentStep(Base):
    __tablename__ = "platform_deployment_steps"
    __table_args__ = (
        Index("ix_platform_deployment_steps_status", "status", "started_at"),
    )

    change_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_deployment_leases.change_id", ondelete="RESTRICT"), primary_key=True
    )
    step_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    step_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="running")
    lease_token: Mapped[uuid.UUID] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verifier_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    unknown_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
