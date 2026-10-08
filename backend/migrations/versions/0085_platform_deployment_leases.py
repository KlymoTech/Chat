"""Add fail-closed durable execution ownership without re-approving old changes."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0085_platform_deployment_leases"
down_revision = "0084_platform_alert_notification_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_deployment_leases",
        sa.Column("change_id", sa.Uuid(), sa.ForeignKey("platform_changes.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("target_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="ready"),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("owner", sa.String(160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_platform_deployment_leases_status_expires",
        "platform_deployment_leases", ["status", "lease_expires_at"],
    )
    # Intentionally do not backfill old approved changes. They require manual
    # reconciliation of qualification proofs and observed infrastructure.


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM platform_deployment_leases")):
        raise RuntimeError("Reconcile deployment lease history before downgrade")
    op.drop_index("ix_platform_deployment_leases_status_expires", table_name="platform_deployment_leases")
    op.drop_table("platform_deployment_leases")
