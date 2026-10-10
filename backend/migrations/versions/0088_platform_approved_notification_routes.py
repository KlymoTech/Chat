"""Create tenant-scoped notification route records, disabled by default."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0088_platform_approved_notification_routes"
down_revision = "0087_platform_deployment_worker_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_approved_notification_routes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("destination_reference", sa.String(200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "channel", name="uq_platform_approved_notification_route"),
        sa.CheckConstraint("channel IN ('email', 'webhook')", name="ck_platform_notification_route_channel"),
        sa.CheckConstraint("revision >= 1", name="ck_platform_notification_route_revision"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM platform_approved_notification_routes")):
        raise RuntimeError("Export and reconcile all notification route records before downgrade")
    op.drop_table("platform_approved_notification_routes")
