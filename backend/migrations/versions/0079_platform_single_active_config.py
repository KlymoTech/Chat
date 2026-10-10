"""Ensure at most one active desired-state revision per environment.

Existing duplicates are a release blocker, not an invitation to discard data.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0079_platform_single_active_config"
down_revision = "0078_source_retrieval_mode"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_platform_config_versions_one_active_per_environment"


def upgrade() -> None:
    conn = op.get_bind()
    duplicates = conn.execute(
        sa.text(
            "SELECT environment FROM platform_config_versions "
            "WHERE active = :enabled GROUP BY environment HAVING COUNT(*) > 1"
        ),
        {"enabled": True},
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            "Multiple active platform configurations exist. Reconcile and audit "
            "them manually before applying revision 0079."
        )
    op.create_index(
        INDEX_NAME,
        "platform_config_versions",
        ["environment"],
        unique=True,
        postgresql_where=sa.text("active = true"),
        sqlite_where=sa.text("active = 1"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="platform_config_versions")
