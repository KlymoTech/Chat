"""Shared authorization, serialization, and evidence loading for knowledge routes."""

from __future__ import annotations

import zipfile
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import KnowledgeKind, KnowledgeSource, KnowledgeStatus
from northstar_api.routers.agents import scoped_agent
from northstar_api.schemas import KnowledgeOut
from northstar_api.security import Principal
from northstar_api.services.education_knowledge import require_education_agent
from northstar_api.services.hybrid_extraction import ExtractionPackage
from northstar_api.services.object_store import object_store


def source_response(source: KnowledgeSource) -> KnowledgeOut:
    """Map the persistence model to the stable knowledge API contract."""
    return KnowledgeOut(
        id=source.id,
        workspace_id=source.workspace_id,
        agent_id=source.agent_id,
        name=source.name,
        kind=source.kind,
        status=source.status,
        size_label=source.size_label,
        chunks=source.chunk_count,
        updated_at=source.updated_at,
        url=source.url,
        content=source.content if source.kind == KnowledgeKind.TEXT else None,
        error=source.error,
        # Older rows created before the non-null default may still deserialize
        # with a null count; API contracts always expose a numeric value.
        extraction_issue_count=source.extraction_issue_count or 0,
        extraction_available=bool(source.extraction_key),
        retrieval_mode=source.retrieval_mode or "lexical",
    )


async def scoped_source(
    source_id: UUID,
    *,
    principal: Principal,
    session: AsyncSession,
) -> KnowledgeSource:
    """Load a source visible to the principal and verify its Education agent."""
    source = await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == principal.tenant_id,
            KnowledgeSource.workspace_id == principal.workspace_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        source.agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    await require_education_agent(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent=agent,
    )
    return source


async def review_source(
    source_id: UUID,
    principal: Principal,
    session: AsyncSession,
) -> KnowledgeSource:
    """Load and lock a source used by the extraction-review workflow."""
    source = await session.scalar(
        select(KnowledgeSource)
        .with_for_update()
        .where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == principal.tenant_id,
            KnowledgeSource.workspace_id == principal.workspace_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    await scoped_agent(
        session,
        principal.tenant_id,
        source.agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    return source


async def load_extraction(source: KnowledgeSource) -> ExtractionPackage:
    """Load immutable extraction evidence and translate invalid archives to HTTP errors."""
    if not source.extraction_key or not source.extraction_key.startswith(
        f"extractions/{source.tenant_id}/{source.id}/"
    ):
        raise HTTPException(status_code=404, detail="Extraction evidence is not available")
    blob, _ = await object_store.download(source.extraction_key, limit_bytes=1024 * 1024 * 1024)
    try:
        return ExtractionPackage.from_archive(blob, source_sha256=source.checksum, revision=source.revision)
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile):
        if source.status == KnowledgeStatus.PROCESSING:
            raise HTTPException(
                status_code=409,
                detail="Extraction is still processing; review evidence will be available when processing completes.",
            ) from None
        raise HTTPException(status_code=409, detail="Extraction evidence is invalid or changed") from None


def size_label(size_bytes: int) -> str:
    """Format an uploaded object size for the browser contract."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"
