"""Add persistent workspace invitations.

Revision ID: 0027_workspace_invitations
Revises: 0026_mfa
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_workspace_invitations"
down_revision = "0026_mfa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "workspace_invitations" in tables:
        return
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invitations_token_hash"),
    )
    op.create_index("ix_workspace_invitations_tenant_id", "workspace_invitations", ["tenant_id"])
    op.create_index("ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"])
    op.create_index("ix_workspace_invitations_email", "workspace_invitations", ["email"])
    op.create_index("ix_workspace_invitations_token_hash", "workspace_invitations", ["token_hash"])
    op.create_index(
        "ix_workspace_invitations_workspace_email",
        "workspace_invitations",
        ["workspace_id", "email"],
    )
    op.create_index(
        "ix_workspace_invitations_tenant_status",
        "workspace_invitations",
        ["tenant_id", "accepted_at", "revoked_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "workspace_invitations" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("workspace_invitations")
