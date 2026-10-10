"""Add qualification approval separation and optimistic revision."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0091_notification_qualification_governance"
down_revision = "0090_platform_notification_worker_qualification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "platform_notification_worker_qualifications"
    op.add_column(table, sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    for name in ("issued_by", "approved_by", "revoked_by"):
        op.add_column(table, sa.Column(name, sa.String(128), nullable=True))
    op.create_check_constraint(
        "ck_notification_qualification_independent_approval", table,
        "approved_by IS NULL OR issued_by IS NULL OR approved_by <> issued_by",
    )


def downgrade() -> None:
    table = "platform_notification_worker_qualifications"
    if op.get_bind().scalar(sa.text(
        "SELECT COUNT(*) FROM platform_notification_worker_qualifications "
        "WHERE revision <> 1 OR issued_by IS NOT NULL OR approved_by IS NOT NULL OR revoked_by IS NOT NULL"
    )):
        raise RuntimeError("Reconcile qualification governance records before downgrade")
    op.drop_constraint("ck_notification_qualification_independent_approval", table, type_="check")
    for name in ("revoked_by", "approved_by", "issued_by", "revision"):
        op.drop_column(table, name)
