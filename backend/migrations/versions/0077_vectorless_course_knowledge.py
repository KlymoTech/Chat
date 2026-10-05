"""Make Course Knowledge indexing lexical while preserving old records.

New Course Knowledge entries do not use embeddings. Existing vector columns
remain nullable compatibility fields so this migration never deletes historic
content; the unused HNSW index is removed and the lexical GIN index remains.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0077_vectorless_course_knowledge"
down_revision = "0076_simplified_course_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column("course_knowledge_index_entries", "embedding", nullable=True)
        op.alter_column(
            "course_knowledge_index_entries",
            "embedding_model",
            existing_type=sa.String(length=240),
            nullable=True,
        )
        op.execute("DROP INDEX IF EXISTS ix_ck_entries_vector")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ck_entries_fts "
            "ON course_knowledge_index_entries USING gin (to_tsvector('simple', content))"
        )
    else:
        with op.batch_alter_table("course_knowledge_index_entries") as batch:
            batch.alter_column("embedding", nullable=True)
            batch.alter_column(
                "embedding_model", existing_type=sa.String(length=240), nullable=True
            )


def downgrade() -> None:
    # A safe downgrade would require re-embedding vectorless rows first.
    pass
