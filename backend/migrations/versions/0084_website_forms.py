"""Site forms and immutable submission evidence, built on existing leads.

Revision ID: 0084_website_forms
Revises: 0083_website_cms_redirects
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0084_website_forms"
down_revision = "0083_website_cms_redirects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_forms",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_version", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_website_forms_workspace_slug"),
    )
    op.create_index("ix_website_forms_tenant_workspace", "website_forms", ["tenant_id", "workspace_id"])
    op.create_table(
        "website_form_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("form_id", sa.Uuid(), sa.ForeignKey("website_forms.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document_json", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("form_id", "version", name="uq_website_form_revision_version"),
    )
    op.create_index("ix_website_form_revisions_form_id", "website_form_revisions", ["form_id"])
    op.create_table(
        "website_form_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("form_id", sa.Uuid(), sa.ForeignKey("website_forms.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("form_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("values_json", sa.JSON().with_variant(JSONB, "postgresql"), nullable=False),
        sa.Column("lead_id", sa.Uuid(), sa.ForeignKey("leads.id", ondelete="RESTRICT")),
        sa.Column("conversion_event_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("form_id", "idempotency_key", name="uq_website_form_submission_key"),
    )
    op.create_index(
        "ix_website_form_submission_workspace_time",
        "website_form_submissions", ["tenant_id", "workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_website_form_submission_workspace_time", table_name="website_form_submissions")
    op.drop_table("website_form_submissions")
    op.drop_index("ix_website_form_revisions_form_id", table_name="website_form_revisions")
    op.drop_table("website_form_revisions")
    op.drop_index("ix_website_forms_tenant_workspace", table_name="website_forms")
    op.drop_table("website_forms")
