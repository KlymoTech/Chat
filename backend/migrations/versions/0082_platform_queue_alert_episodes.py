"""Add non-destructive persistent queue alert episode state."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0082_platform_queue_alert_episodes"
down_revision = "0081_platform_queue_dispatch_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_queue_alert_episodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope_key", sa.String(120), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("scope_key", "code", name="uq_platform_queue_alert_episode_scope_code"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM platform_queue_alert_episodes")):
        raise RuntimeError("Queue alert history exists; archive and reconcile before downgrade")
    op.drop_table("platform_queue_alert_episodes")
