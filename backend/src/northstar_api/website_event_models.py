"""Strictly allowlisted, consent-controlled first-party page events."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class WebsitePageEvent(Base):
    __tablename__ = "website_page_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "event_id", name="uq_website_page_events_workspace_event"),
        Index("ix_website_page_events_reporting", "tenant_id", "workspace_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    visitor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    block_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
