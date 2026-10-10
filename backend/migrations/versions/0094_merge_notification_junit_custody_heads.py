"""Merge the two independent append-only Jenkins JUnit custody migrations.

Both 0093 revisions must run. This merge never drops, rewrites or copies any
existing receipt: Alembic traverses both parents before marking 0094 current.
"""
from __future__ import annotations

revision = "0094_merge_notification_junit_custody_heads"
down_revision = (
    "0093_notification_jenkins_junit_custody",
    "0093_notification_junit_index_custody",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Both immutable custody tables are retained without data mutation."""


def downgrade() -> None:
    """The merge point may be reverted; custody tables stay untouched."""
