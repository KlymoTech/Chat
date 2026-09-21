"""Persist exact accepted-invitation provenance for current Workspace memberships.

Existing memberships are deliberately left unlinked: historical timestamp
correlation cannot prove the invitation used to join. This migration is additive.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0056_workspace_invitation_origin"
down_revision = "0055_workspace_member_suspension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_member_invitation_origins",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "user_id"],
            ["workspace_memberships.workspace_id", "workspace_memberships.user_id"],
            ondelete="CASCADE", name="fk_workspace_member_invitation_origins_membership",
        ),
        sa.ForeignKeyConstraint(["invitation_id"], ["workspace_invitations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
        sa.UniqueConstraint("invitation_id", name="uq_workspace_member_invitation_origins_invitation_id"),
    )
    op.create_index(
        "ix_workspace_member_invitation_origins_tenant_id",
        "workspace_member_invitation_origins", ["tenant_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute('ALTER TABLE "workspace_member_invitation_origins" ENABLE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "workspace_member_invitation_origins" '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON "workspace_member_invitation_origins" TO northstar_app'
        )


def downgrade() -> None:
    op.drop_table("workspace_member_invitation_origins")
