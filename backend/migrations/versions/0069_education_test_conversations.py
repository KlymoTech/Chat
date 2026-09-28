"""Mark staff test conversations of Education agents.

A reviewer can chat with an Education agent as one of its enrolled students before finalizing
training. ``test_mode`` is set only by the staff test endpoint: ``published`` answers exactly as
students see it now; ``unpublished`` also uses approved, indexed material not yet released.
Real student conversations keep NULL and are never affected.

Revision ID: 0069_education_test_conversations
Revises: 0068_platform_execution_report_keys
"""

import sqlalchemy as sa
from alembic import op

revision = "0069_education_test_conversations"
down_revision = "0068_platform_execution_report_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "education_conversation_contexts",
        sa.Column("test_mode", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("education_conversation_contexts", "test_mode")
