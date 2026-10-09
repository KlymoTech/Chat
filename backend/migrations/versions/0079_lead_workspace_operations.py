"""Add durable lead assignment and follow-up records without changing CRM payloads."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0079_lead_workspace_operations"
down_revision = "0078_source_retrieval_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_workspace_operations",
        sa.Column("lead_id", sa.Uuid(), sa.ForeignKey("leads.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_lead_workspace_operations_scope", "lead_workspace_operations", ["tenant_id", "workspace_id"]
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE lead_workspace_operations ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_isolation ON lead_workspace_operations USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON lead_workspace_operations TO northstar_app")


def downgrade() -> None:
    op.drop_table("lead_workspace_operations")
