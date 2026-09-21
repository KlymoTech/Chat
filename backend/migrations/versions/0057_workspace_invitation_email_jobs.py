"""Add a secret-bearing, tenant-isolated invitation email command table.

Only ciphertext is persisted here; ordinary audit and outbox remain secret-free.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0057_workspace_invite_email_jobs"
down_revision = "0056_workspace_invitation_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_invitation_email_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), sa.ForeignKey("workspace_invitations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="queued", nullable=False),
        sa.Column("dispatch_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_workspace_invitation_email_jobs_tenant_workspace",
        "workspace_invitation_email_jobs", ["tenant_id", "workspace_id"],
    )
    op.create_index(
        "ix_workspace_invitation_email_jobs_dispatch",
        "workspace_invitation_email_jobs", ["status", "next_dispatch_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute('ALTER TABLE "workspace_invitation_email_jobs" ENABLE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY tenant_isolation ON "workspace_invitation_email_jobs" '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "workspace_invitation_email_jobs" TO northstar_app')


def downgrade() -> None:
    op.drop_table("workspace_invitation_email_jobs")
