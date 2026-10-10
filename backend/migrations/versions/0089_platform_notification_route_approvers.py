"""Add proposal and approval identity fields to notification routes."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0089_platform_notification_route_approvers"
down_revision = "0088_platform_approved_notification_routes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_approved_notification_routes", sa.Column("proposed_by", sa.Uuid(), nullable=True))
    op.add_column("platform_approved_notification_routes", sa.Column("approved_by", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        "ck_platform_notification_route_separation",
        "platform_approved_notification_routes",
        "approved_by IS NULL OR proposed_by IS NULL OR approved_by <> proposed_by",
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM platform_approved_notification_routes "
        "WHERE proposed_by IS NOT NULL OR approved_by IS NOT NULL"
    )):
        raise RuntimeError("Reconcile approved route governance identities before downgrade")
    op.drop_constraint(
        "ck_platform_notification_route_separation",
        "platform_approved_notification_routes", type_="check",
    )
    op.drop_column("platform_approved_notification_routes", "approved_by")
    op.drop_column("platform_approved_notification_routes", "proposed_by")
