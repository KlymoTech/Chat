"""Add tenant-isolated owner-operated website CMS pages with immutable revisions.

Revision ID: 0079_website_cms_pages
Revises: 0078_source_retrieval_mode
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0079_website_cms_pages"
down_revision = "0078_source_retrieval_mode"
branch_labels = None
depends_on = None

content_json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "website_cms_pages",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("draft_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_website_cms_pages_workspace_slug"),
    )
    op.create_index("ix_website_cms_pages_tenant_workspace", "website_cms_pages", ["tenant_id", "workspace_id"])
    op.create_table(
        "website_cms_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("page_id", sa.Uuid(), sa.ForeignKey("website_cms_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document_json", content_json, nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("page_id", "version", name="uq_website_cms_revisions_page_version"),
    )
    op.create_index("ix_website_cms_revisions_page_id", "website_cms_revisions", ["page_id"])
    op.create_table(
        "website_cms_audit",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("page_id", sa.Uuid(), sa.ForeignKey("website_cms_pages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("revision_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_website_cms_audit_page_id", "website_cms_audit", ["page_id"])


def downgrade() -> None:
    op.drop_index("ix_website_cms_audit_page_id", table_name="website_cms_audit")
    op.drop_table("website_cms_audit")
    op.drop_index("ix_website_cms_revisions_page_id", table_name="website_cms_revisions")
    op.drop_table("website_cms_revisions")
    op.drop_index("ix_website_cms_pages_tenant_workspace", table_name="website_cms_pages")
    op.drop_table("website_cms_pages")
