"""Persist notification worker qualification evidence, disabled by default."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0090_platform_notification_worker_qualification"
down_revision = "0089_platform_notification_route_approvers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_notification_worker_qualifications",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("target_digest", sa.String(64), nullable=False),
        sa.Column("proof_tokens", sa.JSON(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM platform_notification_worker_qualifications")):
        raise RuntimeError("Archive and reconcile qualification evidence before downgrade")
    op.drop_table("platform_notification_worker_qualifications")
