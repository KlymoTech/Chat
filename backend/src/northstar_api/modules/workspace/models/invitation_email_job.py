"""Durable, separately encrypted Workspace invitation mail commands.

Never place raw invite tokens in broker messages, ordinary outbox or audit.
The ciphertext is purged when a job is sent or invalidated.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class WorkspaceInvitationEmailJob(Base):
    __tablename__ = "workspace_invitation_email_jobs"
    __table_args__ = (
        Index("ix_workspace_invitation_email_jobs_tenant_workspace", "tenant_id", "workspace_id"),
        Index("ix_workspace_invitation_email_jobs_dispatch", "status", "next_dispatch_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace_invitations.id", ondelete="CASCADE"), nullable=False,
    )
    ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", server_default="queued")
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
