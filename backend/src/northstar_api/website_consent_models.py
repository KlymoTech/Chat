"""Append-only, tenant-scoped first-party website consent receipts."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class WebsiteConsentReceipt(Base):
    __tablename__ = "website_consent_receipts"
    __table_args__ = (
        Index("ix_website_consent_latest", "workspace_id", "visitor_hash", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
    )
    visitor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analytics: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    marketing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    personalization: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gpc_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="preferences")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
