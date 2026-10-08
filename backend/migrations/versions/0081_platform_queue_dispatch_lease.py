"""Add recoverable leased dispatch metadata without deleting admitted jobs."""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op

revision = "0081_platform_queue_dispatch_lease"
down_revision = "0080_platform_durable_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_durable_jobs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("platform_durable_jobs", sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("platform_durable_jobs", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column("platform_durable_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("platform_durable_jobs", sa.Column("published_reference", sa.String(200), nullable=True))
    op.create_index("ix_platform_durable_jobs_dispatch", "platform_durable_jobs", ["status", "available_at"])


def downgrade() -> None:
    # An operational rollback must not erase leases/receipts with pending work.
    count = op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM platform_durable_jobs"))
    if count:
        raise RuntimeError("Queue dispatch metadata exists; drain/reconcile all jobs before schema downgrade")
    op.drop_index("ix_platform_durable_jobs_dispatch", table_name="platform_durable_jobs")
    for column in ("published_reference", "lease_expires_at", "lease_token", "available_at", "attempts"):
        op.drop_column("platform_durable_jobs", column)
