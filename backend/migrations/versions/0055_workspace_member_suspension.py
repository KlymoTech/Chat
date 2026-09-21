"""Add reversible workspace-scoped member suspension state.

The new table is feature-owned and additive. Existing workspace membership rows
and the global user account stay untouched, so suspension is reversible and
cannot accidentally disable organization access.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0055_workspace_member_suspension"
down_revision = "0054_knowledge_audit_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_member_states",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )
    op.create_index(
        "ix_workspace_member_states_tenant_workspace",
        "workspace_member_states",
        ["tenant_id", "workspace_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute('ALTER TABLE "workspace_member_states" ENABLE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "workspace_member_states" '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "workspace_member_states" TO northstar_app')


def downgrade() -> None:
    op.drop_table("workspace_member_states")
