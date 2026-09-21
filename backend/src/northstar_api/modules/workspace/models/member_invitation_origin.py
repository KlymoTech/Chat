"""Exact invitation provenance for the *current* Workspace membership.

Do not infer the inviter from a historical invitation or similar timestamps.
A composite membership foreign key deletes this record when a member leaves.
No invitation token, hash, link or recipient email is persisted here.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class WorkspaceMemberInvitationOrigin(Base):
    __tablename__ = "workspace_member_invitation_origins"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspace_memberships.workspace_id", "workspace_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_workspace_member_invitation_origins_membership",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    invitation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace_invitations.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
