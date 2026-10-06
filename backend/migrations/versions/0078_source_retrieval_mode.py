"""Persist per-source lexical or PGVector retrieval mode.

This is intentionally additive. Rows created before the toggle are lexical,
and the existing document-chunk vector column/HNSW index is reused only by
sources explicitly trained in PGVector mode.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0078_source_retrieval_mode"
down_revision = "0077_vectorless_course_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_sources",
        sa.Column("retrieval_mode", sa.String(length=20), nullable=False, server_default="lexical"),
    )
    if op.get_bind().dialect.name == "sqlite":
        # SQLite requires a table-rebuild batch operation for an added check.
        with op.batch_alter_table("knowledge_sources") as batch:
            batch.create_check_constraint(
                op.f("ck_knowledge_sources_retrieval_mode"),
                "retrieval_mode IN ('lexical', 'pgvector')",
            )
    else:
        op.create_check_constraint(
            op.f("ck_knowledge_sources_retrieval_mode"),
            "knowledge_sources",
            "retrieval_mode IN ('lexical', 'pgvector')",
        )
    op.create_index(
        "ix_knowledge_sources_retrieval_mode",
        "knowledge_sources",
        ["tenant_id", "workspace_id", "agent_id", "retrieval_mode"],
    )
    op.alter_column("knowledge_sources", "retrieval_mode", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_knowledge_sources_retrieval_mode", table_name="knowledge_sources")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("knowledge_sources") as batch:
            batch.drop_constraint(op.f("ck_knowledge_sources_retrieval_mode"), type_="check")
    else:
        op.drop_constraint(op.f("ck_knowledge_sources_retrieval_mode"), "knowledge_sources", type_="check")
    op.drop_column("knowledge_sources", "retrieval_mode")
