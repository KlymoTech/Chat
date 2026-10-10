"""Database-owned website pages, immutable revisions and audit trail.

The existing application keeps its own Workspace and Tenant models.
Every page query must filter BOTH tenant and workspace boundaries.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base

DocumentJSON = JSON().with_variant(JSONB, "postgresql")


class WebsitePage(Base):
    __tablename__ = "website_cms_pages"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_website_cms_pages_workspace_slug"),
        Index("ix_website_cms_pages_tenant_workspace", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class WebsiteRevision(Base):
    __tablename__ = "website_cms_revisions"
    __table_args__ = (
        UniqueConstraint("page_id", "version", name="uq_website_cms_revisions_page_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("website_cms_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_json: Mapped[dict[str, Any]] = mapped_column(DocumentJSON, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WebsiteAudit(Base):
    __tablename__ = "website_cms_audit"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("website_cms_pages.id", ondelete="RESTRICT"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    revision_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WebsiteSiteMenu(Base):
    """One versioned public navigation document per workspace."""

    __tablename__ = "website_site_menus"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_website_site_menu_workspace"),
        Index("ix_website_site_menus_tenant_workspace", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class WebsiteSiteMenuRevision(Base):
    """Immutable menu content, with the real editor actor."""

    __tablename__ = "website_site_menu_revisions"
    __table_args__ = (
        UniqueConstraint("menu_id", "version", name="uq_website_site_menu_revision_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    menu_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_site_menus.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_json: Mapped[dict[str, Any]] = mapped_column(DocumentJSON, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class WebsiteSiteMenuAudit(Base):
    """Preserve who changed the public navigation pointer and when."""

    __tablename__ = "website_site_menu_audit"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    menu_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_site_menus.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    revision_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class WebsiteRedirect(Base):
    """Per-site immutable source slug with editable, audited destination."""

    __tablename__ = "website_cms_redirects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "source_slug", name="uq_website_cms_redirect_workspace_source"),
        Index("ix_website_cms_redirect_tenant_workspace", "tenant_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    source_slug: Mapped[str] = mapped_column(String(160), nullable=False)
    target_slug: Mapped[str] = mapped_column(String(160), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=308)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class WebsiteRedirectAudit(Base):
    """Preserve every redirection rule change without deleting source history."""

    __tablename__ = "website_cms_redirect_audit"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    redirect_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_cms_redirects.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(DocumentJSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
