"""Add opt-in simplified course configuration without altering legacy courses."""

import sqlalchemy as sa
from alembic import op

revision = "0076_simplified_course_workflow"
down_revision = "0075_course_knowledge_access_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("education_courses", sa.Column("simplified_workflow", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("education_courses", sa.Column("assigned_agent_id", sa.Uuid(), nullable=True))
    op.add_column("education_courses", sa.Column("allowed_channel_connection_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.create_foreign_key("fk_education_courses_assigned_agent", "education_courses", "agents", ["assigned_agent_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_education_courses_assigned_agent_id", "education_courses", ["assigned_agent_id"])
    op.alter_column("education_courses", "simplified_workflow", server_default=None)
    op.alter_column("education_courses", "allowed_channel_connection_ids", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_education_courses_assigned_agent_id", table_name="education_courses")
    op.drop_constraint("fk_education_courses_assigned_agent", "education_courses", type_="foreignkey")
    op.drop_column("education_courses", "allowed_channel_connection_ids")
    op.drop_column("education_courses", "assigned_agent_id")
    op.drop_column("education_courses", "simplified_workflow")
