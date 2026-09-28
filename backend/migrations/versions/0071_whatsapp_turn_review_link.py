"""Link WhatsApp audit turns to academic reviews without rewriting deployed 0070.

Revision ID: 0071_whatsapp_turn_review_link
Revises: 0070_course_faq_whatsapp_audit
"""

import sqlalchemy as sa
from alembic import op

revision = "0071_whatsapp_turn_review_link"
down_revision = "0070_course_faq_whatsapp_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_knowledge_whatsapp_turns",
        sa.Column("review_id", sa.Uuid(), sa.ForeignKey("course_knowledge_academic_reviews.id", ondelete="SET NULL")),
    )
    op.add_column("course_knowledge_whatsapp_turns", sa.Column("review_status", sa.String(20)))


def downgrade() -> None:
    op.drop_column("course_knowledge_whatsapp_turns", "review_status")
    op.drop_column("course_knowledge_whatsapp_turns", "review_id")
