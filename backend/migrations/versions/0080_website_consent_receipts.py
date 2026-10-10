"""Persist append-only, anonymous website consent receipts.

Revision ID: 0080_website_consent_receipts
Revises: 0079_website_cms_pages
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0080_website_consent_receipts"
down_revision = "0079_website_cms_pages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_consent_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visitor_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("analytics", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("marketing", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("personalization", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gpc_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="preferences"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_website_consent_latest", "website_consent_receipts",
        ["workspace_id", "visitor_hash", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_website_consent_latest", table_name="website_consent_receipts")
    op.drop_table("website_consent_receipts")
