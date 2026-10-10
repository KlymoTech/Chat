"""Record only consent-eligible website events with scoped deduplication.

Revision ID: 0081_website_page_events
Revises: 0080_website_consent_receipts
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0081_website_page_events"
down_revision = "0080_website_consent_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_page_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("visitor_hash", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("block_id", sa.String(length=80), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "event_id", name="uq_website_page_events_workspace_event"),
    )
    op.create_index(
        "ix_website_page_events_reporting", "website_page_events",
        ["tenant_id", "workspace_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_website_page_events_reporting", table_name="website_page_events")
    op.drop_table("website_page_events")
