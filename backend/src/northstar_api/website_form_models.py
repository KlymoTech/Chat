"""Form definition/revision/submission models, reusing the existing Lead store."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

FormJSON = JSON().with_variant(JSONB, "postgresql")


class WebsiteForm(Base):
    __tablename__ = "website_forms"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_website_forms_workspace_slug"),
        Index("ix_website_forms_tenant_workspace", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_version: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class WebsiteFormRevision(Base):
    __tablename__ = "website_form_revisions"
    __table_args__ = (UniqueConstraint("form_id", "version", name="uq_website_form_revision_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("website_forms.id", ondelete="RESTRICT"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_json: Mapped[dict[str, Any]] = mapped_column(FormJSON, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WebsiteFormSubmission(Base):
    __tablename__ = "website_form_submissions"
    __table_args__ = (
        UniqueConstraint("form_id", "idempotency_key", name="uq_website_form_submission_key"),
        Index("ix_website_form_submission_workspace_time", "tenant_id", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("website_forms.id", ondelete="RESTRICT"), nullable=False)
    form_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    values_json: Mapped[dict[str, Any]] = mapped_column(FormJSON, nullable=False)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="RESTRICT"))
    conversion_event_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
