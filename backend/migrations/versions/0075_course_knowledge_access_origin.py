"""Mark generated course-knowledge enrollment grants.

Existing records are deliberately treated as manual so no historic student
access is changed by the new bulk synchronization feature.
"""

import sqlalchemy as sa
from alembic import op

revision = "0075_course_knowledge_access_origin"
down_revision = "0074_telegram_managed_bots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_knowledge_enrollment_access",
        sa.Column("access_origin", sa.String(32), nullable=False, server_default="manual"),
    )
    op.alter_column("course_knowledge_enrollment_access", "access_origin", server_default=None)


def downgrade() -> None:
    op.drop_column("course_knowledge_enrollment_access", "access_origin")
