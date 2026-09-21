"""Add reversible workspace-scoped member suspension.

Suspension belongs to a workspace membership, not the global user account. This
keeps organization access and membership history intact and is additive only.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0055_workspace_member_suspension"
down_revision = "0054_knowledge_audit_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_memberships",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_workspace_memberships_workspace_suspended",
        "workspace_memberships",
        ["workspace_id", "suspended_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_memberships_workspace_suspended",
        table_name="workspace_memberships",
    )
    op.drop_column("workspace_memberships", "suspended_at")
