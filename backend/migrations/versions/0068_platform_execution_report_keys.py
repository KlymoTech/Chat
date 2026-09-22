"""Add idempotency keys for deployment execution evidence.

Revision ID: 0068_platform_execution_report_keys
Revises: 0067_platform_control_plane_state
"""

import sqlalchemy as sa
from alembic import op

revision = "0068_platform_execution_report_keys"
down_revision = "0067_platform_control_plane_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platform_deployment_executions",
        sa.Column("report_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "platform_deployment_executions",
        sa.Column("source_digest", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "platform_deployment_executions",
        sa.Column("target_digest", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_platform_deployment_executions_change_report_key",
        "platform_deployment_executions",
        ["change_id", "report_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_platform_deployment_executions_change_report_key",
        "platform_deployment_executions",
        type_="unique",
    )
    op.drop_column("platform_deployment_executions", "report_key")
    op.drop_column("platform_deployment_executions", "source_digest")
    op.drop_column("platform_deployment_executions", "target_digest")
