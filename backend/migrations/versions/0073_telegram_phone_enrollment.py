"""Add Telegram contact enrollment and reply-keyboard persistence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0073_telegram_phone_enrollment"
down_revision = "0072_release_deleted_agent_whatsapp_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("education_students", sa.Column("telegram_phone_number", sa.String(16), nullable=True))
    op.add_column("education_students", sa.Column("telegram_phone_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_unique_constraint("uq_student_telegram_phone", "education_students", ["workspace_id", "telegram_phone_number"])
    op.add_column("channel_outbound_deliveries", sa.Column("reply_markup", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_outbound_deliveries", "reply_markup")
    op.drop_constraint("uq_student_telegram_phone", "education_students", type_="unique")
    op.drop_column("education_students", "telegram_phone_verified")
    op.drop_column("education_students", "telegram_phone_number")
