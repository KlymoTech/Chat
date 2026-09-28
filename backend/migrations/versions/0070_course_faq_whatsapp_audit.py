"""Teacher-reviewed course FAQ and auditable WhatsApp turns.

Revision ID: 0070_course_faq_whatsapp_audit
Revises: 0069_education_test_conversations
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0070_course_faq_whatsapp_audit"
down_revision = "0069_education_test_conversations"
branch_labels = None
depends_on = None
JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def _boundary() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("course_knowledge_response_contexts", sa.Column("answer_path", sa.String(30), server_default="document", nullable=False))
    op.create_table(
        "course_knowledge_faq_entries",
        *_boundary(),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("education_courses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), sa.ForeignKey("course_knowledge_curricula.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("course_knowledge_papers.id", ondelete="RESTRICT")),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("education_batches.id", ondelete="RESTRICT")),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("variants", JSON, nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("language", sa.String(80), nullable=False),
        sa.Column("references", JSON, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column("review_id", sa.Uuid(), sa.ForeignKey("course_knowledge_academic_reviews.id", ondelete="SET NULL")),
        sa.CheckConstraint("status IN ('draft', 'approved', 'withdrawn')", name="ck_faq_status"),
    )
    op.create_index("ix_ck_faq_audience", "course_knowledge_faq_entries", ["tenant_id", "workspace_id", "agent_id", "course_id", "curriculum_id", "paper_id", "batch_id"])
    for column in ("tenant_id", "workspace_id", "agent_id"):
        op.create_index(f"ix_course_knowledge_faq_entries_{column}", "course_knowledge_faq_entries", [column])
    op.create_table(
        "course_knowledge_whatsapp_turns",
        *_boundary(),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        sa.Column("question_message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("answer_message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("enrollment_id", sa.Uuid(), sa.ForeignKey("education_enrollments.id", ondelete="SET NULL")),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("education_courses.id", ondelete="SET NULL")),
        sa.Column("curriculum_id", sa.Uuid(), sa.ForeignKey("course_knowledge_curricula.id", ondelete="SET NULL")),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("course_knowledge_papers.id", ondelete="SET NULL")),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("education_batches.id", ondelete="SET NULL")),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("answer_path", sa.String(30), nullable=False),
        sa.Column("delivery_status", sa.String(30), nullable=False),
        sa.Column("citations", JSON, nullable=False),
        sa.Column("context_fingerprint", sa.String(64)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("provider_message_ids", JSON, nullable=False),
        sa.Column("error", sa.String(500)),
        sa.UniqueConstraint("receipt_id", name="uq_ck_whatsapp_turn_receipt"),
    )
    for column in ("tenant_id", "workspace_id", "agent_id"):
        op.create_index(f"ix_course_knowledge_whatsapp_turns_{column}", "course_knowledge_whatsapp_turns", [column])
    op.create_index("ix_course_knowledge_whatsapp_turns_receipt_id", "course_knowledge_whatsapp_turns", ["receipt_id"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("course_knowledge_faq_entries", "course_knowledge_whatsapp_turns"):
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO northstar_app")
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"CREATE POLICY tenant_isolation ON {table} USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)")


def downgrade() -> None:
    op.drop_table("course_knowledge_whatsapp_turns")
    op.drop_table("course_knowledge_faq_entries")
    op.drop_column("course_knowledge_response_contexts", "answer_path")
