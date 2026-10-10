"""Add protected and actor-audited site redirects to existing website CMS.

Revision ID: 0083_website_cms_redirects
Revises: 0082_website_site_navigation
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0083_website_cms_redirects"
down_revision = "0082_website_site_navigation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_cms_redirects",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_slug", sa.String(length=160), nullable=False),
        sa.Column("target_slug", sa.String(length=160), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False, server_default="308"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "source_slug", name="uq_website_cms_redirect_workspace_source"),
    )
    op.create_index(
        "ix_website_cms_redirect_tenant_workspace", "website_cms_redirects", ["tenant_id", "workspace_id"],
    )
    op.create_table(
        "website_cms_redirect_audit",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("redirect_id", sa.Uuid(), sa.ForeignKey("website_cms_redirects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_website_cms_redirect_audit_redirect_id", "website_cms_redirect_audit", ["redirect_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_website_cms_redirect_audit_redirect_id", table_name="website_cms_redirect_audit")
    op.drop_table("website_cms_redirect_audit")
    op.drop_index("ix_website_cms_redirect_tenant_workspace", table_name="website_cms_redirects")
    op.drop_table("website_cms_redirects")
