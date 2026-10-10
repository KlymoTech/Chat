"""Add revisioned first-party navigation within the existing CMS.

Revision ID: 0082_website_site_navigation
Revises: 0081_website_page_events
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0082_website_site_navigation"
down_revision = "0081_website_page_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_site_menus",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", name="uq_website_site_menu_workspace"),
    )
    op.create_index(
        "ix_website_site_menus_tenant_workspace", "website_site_menus", ["tenant_id", "workspace_id"],
    )
    op.create_table(
        "website_site_menu_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("menu_id", sa.Uuid(), sa.ForeignKey("website_site_menus.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document_json", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("menu_id", "version", name="uq_website_site_menu_revision_version"),
    )
    op.create_index(
        "ix_website_site_menu_revisions_menu_id", "website_site_menu_revisions", ["menu_id"],
    )
    op.create_table(
        "website_site_menu_audit",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("menu_id", sa.Uuid(), sa.ForeignKey("website_site_menus.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("revision_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_website_site_menu_audit_menu_id", "website_site_menu_audit", ["menu_id"])


def downgrade() -> None:
    op.drop_index("ix_website_site_menu_audit_menu_id", table_name="website_site_menu_audit")
    op.drop_table("website_site_menu_audit")
    op.drop_index("ix_website_site_menu_revisions_menu_id", table_name="website_site_menu_revisions")
    op.drop_table("website_site_menu_revisions")
    op.drop_index("ix_website_site_menus_tenant_workspace", table_name="website_site_menus")
    op.drop_table("website_site_menus")
