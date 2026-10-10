"""Durable website automations, scoped to existing workspaces and leads.

This is not an alternate CRM, contact system or marketing delivery queue.
Definitions are immutable by version. Internal work is idempotent and paused
when its workflow is disabled or its associated lead loses consent.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Index, Integer, String,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

DocumentJSON = JSON().with_variant(JSONB, "postgresql")


class WebsiteAutomation(Base):
    __tablename__ = "website_automations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_website_automation_scope_slug"),
        Index("ix_website_automations_scope", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_version: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class WebsiteAutomationRevision(Base):
    __tablename__ = "website_automation_revisions"
    __table_args__ = (
        UniqueConstraint("automation_id", "version", name="uq_website_automation_revision_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_automations.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_json: Mapped[dict[str, Any]] = mapped_column(DocumentJSON, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class WebsiteAutomationRun(Base):
    __tablename__ = "website_automation_runs"
    __table_args__ = (
        UniqueConstraint("automation_id", "trigger_key", name="uq_website_automation_run_trigger"),
        Index("ix_website_automation_run_due", "status", "due_at"),
        Index("ix_website_automation_run_workspace", "tenant_id", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_automations.id", ondelete="RESTRICT"), nullable=False,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    trigger_key: Mapped[str] = mapped_column(String(130), nullable=False)
    published_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_node_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_category: Mapped[str] = mapped_column(String(32), nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )
