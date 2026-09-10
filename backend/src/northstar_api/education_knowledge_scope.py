from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from northstar_api.database import Base


class EducationKnowledgeScope(Base):
    """Bind existing Agent knowledge to one authorized Course + Batch pair.

    A row targets exactly one existing knowledge source or standalone fact. Document
    chunks inherit the scope of their source, so the existing ingestion/vector
    pipeline remains unchanged.
    """

    __tablename__ = "education_knowledge_scopes"
    __table_args__ = (
        CheckConstraint(
            "(source_id IS NOT NULL AND fact_id IS NULL) OR "
            "(source_id IS NULL AND fact_id IS NOT NULL)",
            name="ck_education_knowledge_scope_target",
        ),
        UniqueConstraint(
            "source_id",
            "course_id",
            "batch_id",
            name="uq_education_knowledge_scope_source",
        ),
        UniqueConstraint(
            "fact_id",
            "course_id",
            "batch_id",
            name="uq_education_knowledge_scope_fact",
        ),
        Index(
            "ix_education_knowledge_scope_lookup",
            "tenant_id",
            "workspace_id",
            "agent_id",
            "course_id",
            "batch_id",
        ),
        Index("ix_education_knowledge_scope_source_id", "source_id"),
        Index("ix_education_knowledge_scope_fact_id", "fact_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=True
    )
    fact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_facts.id", ondelete="CASCADE"), nullable=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_courses.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("education_batches.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
