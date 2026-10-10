"""Versioned internal-only website automations on existing Lead records.

Revision ID: 0085_website_automations
Revises: 0084_website_forms
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0085_website_automations"
down_revision = "0084_website_forms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_automations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_version", sa.Integer()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_website_automation_scope_slug"),
    )
    op.create_index("ix_website_automations_scope", "website_automations", ["tenant_id", "workspace_id"])
    op.create_table(
        "website_automation_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("automation_id", sa.Uuid(), sa.ForeignKey("website_automations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document_json", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("automation_id", "version", name="uq_website_automation_revision_version"),
    )
    op.create_index(
        "ix_website_automation_revisions_automation_id",
        "website_automation_revisions", ["automation_id"],
    )
    op.create_table(
        "website_automation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("automation_id", sa.Uuid(), sa.ForeignKey("website_automations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("lead_id", sa.Uuid(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_key", sa.String(130), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=False),
        sa.Column("current_node_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_category", sa.String(32), nullable=False),
        sa.Column("last_error", sa.String(240)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("automation_id", "trigger_key", name="uq_website_automation_run_trigger"),
    )
    op.create_index("ix_website_automation_run_due", "website_automation_runs", ["status", "due_at"])
    op.create_index(
        "ix_website_automation_run_workspace", "website_automation_runs",
        ["tenant_id", "workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_website_automation_run_workspace", table_name="website_automation_runs")
    op.drop_index("ix_website_automation_run_due", table_name="website_automation_runs")
    op.drop_table("website_automation_runs")
    op.drop_index("ix_website_automation_revisions_automation_id", table_name="website_automation_revisions")
    op.drop_table("website_automation_revisions")
    op.drop_index("ix_website_automations_scope", table_name="website_automations")
    op.drop_table("website_automations")
