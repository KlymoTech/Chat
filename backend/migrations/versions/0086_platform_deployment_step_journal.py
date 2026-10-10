"""Add durable step checkpoints after the fenced worker lease migration.

Old changes are not backfilled and cannot silently acquire verified steps.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0086_platform_deployment_step_journal"
down_revision = "0085_platform_deployment_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_deployment_steps",
        sa.Column(
            "change_id", sa.Uuid(),
            sa.ForeignKey("platform_deployment_leases.change_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("step_index", sa.Integer(), primary_key=True),
        sa.Column("step_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_digest", sa.String(64), nullable=True),
        sa.Column("verifier_run_id", sa.String(128), nullable=True),
        sa.Column("unknown_reason", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_platform_deployment_steps_status", "platform_deployment_steps",
        ["status", "started_at"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM platform_deployment_steps")):
        raise RuntimeError("Reconcile and export deployment step evidence before downgrade")
    op.drop_index("ix_platform_deployment_steps_status", table_name="platform_deployment_steps")
    op.drop_table("platform_deployment_steps")
