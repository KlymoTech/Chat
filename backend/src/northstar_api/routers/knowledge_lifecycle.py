"""Deletion and asynchronous-job routes for knowledge sources."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Response
from sqlalchemy import select

from northstar_api.models import IngestionJob, KnowledgeSource
from northstar_api.routers.knowledge_routes import (
    DB,
    KnowledgeManagePrincipal,
    KnowledgeViewPrincipal,
    router,
)
from northstar_api.schemas import JobOut, KnowledgeUntrain
from northstar_api.services.outbox import enqueue_event


@router.post("/knowledge/untrain")
async def untrain_knowledge(
    payload: KnowledgeUntrain,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> dict[str, int]:
    sources = list(
        await session.scalars(
            select(KnowledgeSource).where(
                KnowledgeSource.id.in_(payload.source_ids),
                KnowledgeSource.tenant_id == principal.tenant_id,
                KnowledgeSource.workspace_id == principal.workspace_id,
            )
        )
    )
    if len(sources) != len(payload.source_ids):
        raise HTTPException(status_code=404, detail="One or more knowledge sources were not found")
    removed_chunks = sum(source.chunk_count for source in sources)
    for source in sources:
        await session.delete(source)
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="knowledge_source",
            aggregate_id=source.id,
            event_type="knowledge.source.deleted.v1",
            payload={
                "sourceId": str(source.id),
                "agentId": str(source.agent_id),
                "objectKey": source.object_key,
                "extractionKey": source.extraction_key,
            },
        )
    await session.commit()
    return {"removedSources": len(sources), "removedChunks": removed_chunks}


@router.delete("/knowledge/{source_id}", status_code=204)
async def delete_knowledge(
    source_id: UUID,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> Response:
    source = await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == principal.tenant_id,
            KnowledgeSource.workspace_id == principal.workspace_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    await session.delete(source)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="knowledge.source.deleted.v1",
        payload={
            "sourceId": str(source.id),
            "agentId": str(source.agent_id),
            "objectKey": source.object_key,
            "extractionKey": source.extraction_key,
        },
    )
    await session.commit()
    return Response(status_code=204)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: UUID, principal: KnowledgeViewPrincipal, session: DB) -> JobOut:
    job = await session.scalar(
        select(IngestionJob).where(
            IngestionJob.id == job_id,
            IngestionJob.tenant_id == principal.tenant_id,
            IngestionJob.workspace_id == principal.workspace_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut(
        id=job.id,
        source_id=job.source_id,
        status=job.status,
        step=job.step,
        progress=job.progress,
        attempts=job.attempts,
        error=job.error_json,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
