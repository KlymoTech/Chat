"""Add independent idempotent admission rows for future queue adapters."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0080_platform_durable_jobs"
down_revision = "0079_platform_single_active_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_durable_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("payload_reference", sa.String(length=500), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_platform_durable_jobs_tenant_key"),
    )
    op.create_index("ix_platform_durable_jobs_status_created", "platform_durable_jobs", ["status", "created_at"])


def downgrade() -> None:
    # Refuse destructive rollback while accepted work remains.
    count = op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM platform_durable_jobs"))
    if count:
        raise RuntimeError("Durable jobs still exist; archive and reconcile before schema downgrade")
    op.drop_index("ix_platform_durable_jobs_status_created", table_name="platform_durable_jobs")
    op.drop_table("platform_durable_jobs")
