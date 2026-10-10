"""Add durable notification outbox; never send messages in a migration."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0083_platform_queue_alert_notifications"
down_revision = "0082_platform_queue_alert_episodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_queue_alert_notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("episode_id", sa.Uuid(), sa.ForeignKey("platform_queue_alert_episodes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_platform_queue_alert_notification_dedupe"),
    )
    op.create_index(
        "ix_platform_queue_alert_notifications_due",
        "platform_queue_alert_notifications", ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM platform_queue_alert_notifications")):
        raise RuntimeError("Archive/reconcile notification history before downgrade")
    op.drop_index("ix_platform_queue_alert_notifications_due", table_name="platform_queue_alert_notifications")
    op.drop_table("platform_queue_alert_notifications")
