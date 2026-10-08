"""Add recoverable notification claims without dropping existing outbox rows."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0084_platform_alert_notification_leases"
down_revision = "0083_platform_queue_alert_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_queue_alert_notifications", sa.Column("lease_token", sa.Uuid(), nullable=True))
    op.add_column("platform_queue_alert_notifications", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("platform_queue_alert_notifications", sa.Column("provider_reference", sa.String(200), nullable=True))


def downgrade() -> None:
    count = op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM platform_queue_alert_notifications "
        "WHERE lease_token IS NOT NULL OR provider_reference IS NOT NULL"
    ))
    if count:
        raise RuntimeError("Reconcile notification leases and receipts before downgrade")
    for column in ("provider_reference", "lease_expires_at", "lease_token"):
        op.drop_column("platform_queue_alert_notifications", column)
