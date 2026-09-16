from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education_knowledge_schemas import (
    EducationKnowledgeScopeOut,
    EducationKnowledgeScopeReplace,
)
from northstar_api.models import (
    FactStatus,
    IngestionJob,
    JobStatus,
    KnowledgeFact,
    KnowledgeKind,
    KnowledgeSource,
    KnowledgeStatus,
)
from northstar_api.routers.agents import scoped_agent
from northstar_api.schemas import (
    APIModel,
    FactCreate,
    FactOut,
    FactPatch,
    JobOut,
    KnowledgeCreate,
    KnowledgeOut,
    UploadPresignOut,
    UploadPresignRequest,
)
from northstar_api.security import Principal
from northstar_api.services.education_knowledge import (
    list_fact_scopes,
    list_source_scopes,
    replace_fact_scopes,
    replace_source_scopes,
    require_education_agent,
)
from northstar_api.services.hybrid_extraction import ExtractionPackage
from northstar_api.services.extraction_review import apply_review
from northstar_api.services.extraction_schema import Reading
from northstar_api.services.ingestion import ingest_source_async
from northstar_api.services.llm import nvidia_adapter
from northstar_api.services.object_store import InvalidUpload, ObjectStoreUnavailable, object_store
from northstar_api.services.outbox import enqueue_event

router = APIRouter(tags=["knowledge"])
DB = Annotated[AsyncSession, Depends(get_session)]
KnowledgeViewPrincipal = Annotated[Principal, Depends(require_permissions("knowledge.view"))]
KnowledgeManagePrincipal = Annotated[Principal, Depends(require_permissions("knowledge.manage"))]
logger = structlog.get_logger(__name__)


@router.post("/uploads/presign", response_model=UploadPresignOut)
async def presign_upload(
    payload: UploadPresignRequest, principal: KnowledgeManagePrincipal
) -> UploadPresignOut:
    settings = get_settings()
    if payload.size_bytes > settings.upload_max_bytes:
        limit_mb = settings.upload_max_bytes / (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Files must be {limit_mb:g} MB or smaller.")
    try:
        key, url, fields, expires_at = await object_store.presign_post(
            tenant_id=principal.tenant_id,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            checksum_sha256=payload.checksum_sha256,
        )
    except InvalidUpload as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ObjectStoreUnavailable:
        raise HTTPException(status_code=503, detail="Object storage is not configured") from None
    public_endpoint = urlsplit(settings.s3_public_endpoint_url or "")
    if public_endpoint.hostname in {"localhost", "127.0.0.1"}:
        signed_path = urlsplit(url).path
        if not signed_path.startswith(f"/{settings.s3_bucket}"):
            raise HTTPException(status_code=503, detail="Object storage returned an invalid upload path")
        url = f"/storage{signed_path}"
    return UploadPresignOut(url=url, object_key=key, fields=fields, expires_at=expires_at)


def source_response(source: KnowledgeSource) -> KnowledgeOut:
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
        extraction_issue_count=source.extraction_issue_count,
    )


@router.get("/agents/{agent_id}/knowledge", response_model=list[KnowledgeOut])
async def list_knowledge(
    agent_id: UUID, principal: KnowledgeViewPrincipal, session: DB
) -> list[KnowledgeOut]:
    await scoped_agent(session, principal.tenant_id, agent_id, workspace_id=principal.workspace_id)
    sources = (
        await session.scalars(
            select(KnowledgeSource)
            .where(
                KnowledgeSource.tenant_id == principal.tenant_id,
                KnowledgeSource.workspace_id == principal.workspace_id,
                KnowledgeSource.agent_id == agent_id,
            )
            .order_by(KnowledgeSource.updated_at.desc())
        )
    ).all()
    return [source_response(item) for item in sources]


@router.post("/agents/{agent_id}/knowledge", response_model=KnowledgeOut, status_code=201)
async def add_knowledge(
    agent_id: UUID, payload: KnowledgeCreate, principal: KnowledgeManagePrincipal, session: DB
) -> KnowledgeOut:
    await scoped_agent(session, principal.tenant_id, agent_id, workspace_id=principal.workspace_id)
    if payload.kind == KnowledgeKind.TEXT and not payload.content:
        raise HTTPException(status_code=422, detail="Text sources require content")
    if payload.kind in (KnowledgeKind.URL, KnowledgeKind.SITEMAP) and not payload.url:
        raise HTTPException(status_code=422, detail="URL and sitemap sources require a URL")
    if payload.kind == KnowledgeKind.FILE and not (payload.object_key or payload.content):
        raise HTTPException(status_code=422, detail="File sources require an uploaded object key")
    if payload.object_key and payload.kind != KnowledgeKind.FILE:
        raise HTTPException(status_code=422, detail="Only file sources can reference an uploaded object")

    object_key = payload.object_key
    uploaded_checksum: str | None = None
    uploaded_size: int | None = None
    if object_key:
        try:
            object_key, uploaded_checksum, uploaded_size = await object_store.promote_staged(
                principal.tenant_id, object_key
            )
        except InvalidUpload as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except ObjectStoreUnavailable:
            raise HTTPException(status_code=503, detail="Object storage is unavailable") from None

    raw_identity = payload.content or str(payload.url or object_key)
    source = KnowledgeSource(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=agent_id,
        name=payload.name.strip(),
        kind=payload.kind,
        status=KnowledgeStatus.PROCESSING,
        size_label=_size_label(uploaded_size) if uploaded_size is not None else "Queued",
        url=str(payload.url) if payload.url else None,
        content=payload.content,
        object_key=object_key,
        checksum=uploaded_checksum or hashlib.sha256(raw_identity.encode()).hexdigest(),
    )
    session.add(source)
    await session.flush()
    job = IngestionJob(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        source_id=source.id,
        status=JobStatus.QUEUED,
        idempotency_key=f"ingest:{source.id}:{source.revision}:{source.checksum}",
    )
    session.add(job)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="knowledge.source.created.v1",
        payload={"sourceId": str(source.id), "agentId": str(agent_id), "kind": source.kind.value},
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        if object_key:
            try:
                await object_store.purge_exact(object_key)
            except Exception as cleanup_error:
                logger.warning(
                    "promoted_upload_cleanup_failed",
                    object_key=object_key,
                    error=type(cleanup_error).__name__,
                )
        raise

    settings = get_settings()
    if not settings.background_dispatch_enabled:
        await ingest_source_async(session, source.id)
        await session.refresh(source)
    return source_response(source)


async def _scoped_source(
    source_id: UUID,
    *,
    principal: Principal,
    session: AsyncSession,
) -> KnowledgeSource:
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
    )
    await require_education_agent(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent=agent,
    )
    return source


async def _review_source(source_id: UUID, principal: Principal, session: AsyncSession) -> KnowledgeSource:
    source = await session.scalar(
        select(KnowledgeSource).with_for_update().where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == principal.tenant_id,
            KnowledgeSource.workspace_id == principal.workspace_id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    await scoped_agent(session, principal.tenant_id, source.agent_id, workspace_id=principal.workspace_id)
    return source


async def _load_extraction(source: KnowledgeSource) -> ExtractionPackage:
    if not source.extraction_key or not source.extraction_key.startswith(
        f"extractions/{source.tenant_id}/{source.id}/"
    ):
        raise HTTPException(status_code=404, detail="Extraction evidence is not available")
    blob, _ = await object_store.download(source.extraction_key, limit_bytes=1024 * 1024 * 1024)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members = archive.infolist()
        if len(members) > 200_000 or sum(item.file_size for item in members) > 2 * 1024 * 1024 * 1024:
            raise HTTPException(status_code=409, detail="Extraction evidence exceeds safe archive limits")
        manifest = json.loads(archive.read("manifest.json"))
        names = [m.filename for m in members]
        if len(set(names)) != len(names) or set(names) != set(manifest.get("artifacts", {})) | {"manifest.json"}:
            raise HTTPException(status_code=409, detail="Evidence manifest does not account for every artifact")
        for name, expected in manifest.get("artifacts", {}).items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise HTTPException(status_code=409, detail="Extraction evidence checksum failed")
        record = json.loads(archive.read("extracted.json"))
        images = {name: archive.read(name) for name in archive.namelist() if name not in {"manifest.json", "extracted.json", "extracted_review.txt", "validation_report.txt", "correction_history.json"}}
    if (
        record.get("source_sha256") != source.checksum
        or manifest.get("source_sha256") != source.checksum
        or record.get("expected_units") != len(record.get("pages", []))
        or (
            record.get("extraction_revision") is not None and record["extraction_revision"] != source.revision
        )
    ):
        raise HTTPException(status_code=409, detail="Extraction evidence does not match this source")
    for page in record["pages"]:
        path = page.get("image")
        if path and (
            path not in images or hashlib.sha256(images[path]).hexdigest() != page.get("image_sha256")
        ):
            raise HTTPException(status_code=409, detail="Source page image checksum failed")
    return ExtractionPackage(record=record, images=images)


@router.get("/knowledge/{source_id}/extraction")
async def get_extraction(
    source_id: UUID, principal: KnowledgeViewPrincipal, session: DB
) -> dict[str, object]:
    source = await _review_source(source_id, principal, session)
    return (await _load_extraction(source)).record


@router.get("/knowledge/{source_id}/extraction/pages/{page_number}")
async def get_extraction_page(
    source_id: UUID, page_number: int, principal: KnowledgeViewPrincipal, session: DB
) -> Response:
    source = await _review_source(source_id, principal, session)
    package = await _load_extraction(source)
    path = f"pages/page_{page_number:04d}.png"
    if path not in package.images:
        raise HTTPException(status_code=404, detail="Page image not found")
    return Response(content=package.images[path], media_type="image/png")


@router.get("/knowledge/{source_id}/extraction/report")
async def get_extraction_report(source_id: UUID, principal: KnowledgeViewPrincipal, session: DB) -> Response:
    source = await _review_source(source_id, principal, session)
    return Response(content=(await _load_extraction(source)).validation_text(), media_type="text/plain")


@router.get("/knowledge/{source_id}/extraction/archive")
async def get_extraction_archive(source_id: UUID, principal: KnowledgeViewPrincipal, session: DB) -> Response:
    source = await _review_source(source_id, principal, session)
    package = await _load_extraction(source)
    return Response(
        content=package.archive(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="extraction-review.zip"'},
    )


class ReviewedBlock(APIModel):
    id: str = Field(max_length=100)
    selected_text: str = Field(max_length=200_000)
    structure: Reading | None = None
    related_block_ids: list[str] = Field(default_factory=list, max_length=100)


class ReviewedPage(APIModel):
    number: int = Field(ge=1)
    selected_text: str = Field(max_length=200_000)
    reason: str = Field(min_length=1, max_length=500)
    structure_confirmed: bool = False
    blank_confirmed: bool = False
    blocks: list[ReviewedBlock] = Field(default_factory=list, max_length=1000)


class IssueResolution(APIModel):
    id: str = Field(max_length=100)
    action: Literal["source_verified", "source_anomaly", "unresolved"]
    reason: str = Field(min_length=1, max_length=1000)


class ExtractionApproval(APIModel):
    extraction_revision: int = Field(ge=1)
    pages: list[ReviewedPage] = Field(min_length=1, max_length=5_000)
    issue_resolutions: list[IssueResolution] = Field(default_factory=list, max_length=20000)


@router.post("/knowledge/{source_id}/extraction/retry", response_model=KnowledgeOut)
async def retry_extraction(source_id: UUID, principal: KnowledgeManagePrincipal, session: DB) -> KnowledgeOut:
    source = await _review_source(source_id, principal, session)
    if source.status != KnowledgeStatus.NEEDS_REVIEW or not source.object_key:
        raise HTTPException(status_code=409, detail="Source is not awaiting extraction review")
    source.revision += 1
    source.status = KnowledgeStatus.PROCESSING
    source.error = None
    session.add(
        IngestionJob(
            tenant_id=source.tenant_id,
            workspace_id=source.workspace_id,
            source_id=source.id,
            status=JobStatus.QUEUED,
            idempotency_key=f"ingest:{source.id}:{source.revision}:{source.checksum}",
        )
    )
    enqueue_event(
        session,
        tenant_id=source.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="knowledge.source.created.v1",
        payload={"sourceId": str(source.id), "agentId": str(source.agent_id), "kind": source.kind.value},
    )
    await session.commit()
    if not get_settings().background_dispatch_enabled:
        await ingest_source_async(session, source.id)
        await session.refresh(source)
    return source_response(source)


@router.post("/knowledge/{source_id}/extraction/approve", response_model=KnowledgeOut)
async def approve_extraction(
    source_id: UUID, payload: ExtractionApproval, principal: KnowledgeManagePrincipal, session: DB
) -> KnowledgeOut:
    source = await _review_source(source_id, principal, session)
    if source.status != KnowledgeStatus.NEEDS_REVIEW:
        raise HTTPException(status_code=409, detail="Source is not awaiting extraction review")
    package = await _load_extraction(source)
    if payload.extraction_revision != source.revision:
        raise HTTPException(status_code=409, detail="Evidence changed; reload before reviewing")
    pages = package.record["pages"]
    settings = get_settings()
    if sum(len(item.selected_text) for item in payload.pages) > settings.knowledge_max_extracted_characters:
        raise HTTPException(status_code=413, detail="Reviewed text exceeds the extraction limit")
    try:
        apply_review(package.record, [p.model_dump() for p in payload.pages],
                     [r.model_dump() for r in payload.issue_resolutions], str(principal.user_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    package.refresh()
    released = package.record["release_eligible"]
    package.record["review_status"] = "verified_release" if released else "needs_review"
    selected = [page["selected_text"] for page in pages]
    # Persist the reviewed evidence before scheduling indexing.
    next_revision = source.revision + 1
    package.record["extraction_revision"] = next_revision
    source.extraction_key = await object_store.put_extraction(
        source.tenant_id, source.id, package.archive(), version=next_revision
    )
    source.revision = next_revision
    source.extraction_issue_count = sum(i.get("status") != "resolved" for i in package.issues)
    if not released:
        source.status = KnowledgeStatus.NEEDS_REVIEW
        await session.commit()
        return source_response(source)
    source.content = "\n\n".join(
        f"===PDF_PAGE:{page['number']}===\n{value}" if source.name.lower().endswith(".pdf") else value
        for page, value in zip(pages, selected, strict=True)
    )
    source.extraction_issue_count = 0
    source.status = KnowledgeStatus.PROCESSING
    source.revision = next_revision
    job = IngestionJob(
        tenant_id=source.tenant_id,
        workspace_id=source.workspace_id,
        source_id=source.id,
        status=JobStatus.QUEUED,
        idempotency_key=f"ingest:{source.id}:{source.revision}:{source.checksum}",
    )
    session.add(job)
    enqueue_event(
        session,
        tenant_id=source.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="knowledge.source.created.v1",
        payload={"sourceId": str(source.id), "agentId": str(source.agent_id), "kind": source.kind.value},
    )
    await session.commit()
    if not settings.background_dispatch_enabled:
        await ingest_source_async(session, source.id)
        await session.refresh(source)
    return source_response(source)


@router.get(
    "/knowledge/{source_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def get_source_education_scopes(
    source_id: UUID,
    principal: KnowledgeViewPrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    source = await _scoped_source(source_id, principal=principal, session=session)
    return list(
        await list_source_scopes(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent_id=source.agent_id,
            source_id=source.id,
        )
    )


@router.put(
    "/knowledge/{source_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def set_source_education_scopes(
    source_id: UUID,
    payload: EducationKnowledgeScopeReplace,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    source = await _scoped_source(source_id, principal=principal, session=session)
    scopes = await replace_source_scopes(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=source.agent_id,
        source_id=source.id,
        pairs=payload.scopes,
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="education.knowledge.scope.updated.v1",
        payload={
            "sourceId": str(source.id),
            "agentId": str(source.agent_id),
            "scopes": [{"courseId": str(item.course_id), "batchId": str(item.batch_id)} for item in scopes],
        },
    )
    await session.commit()
    return list(scopes)


@router.delete("/knowledge/{source_id}", status_code=204)
async def delete_knowledge(source_id: UUID, principal: KnowledgeManagePrincipal, session: DB) -> Response:
    source = await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.tenant_id == principal.tenant_id,
            KnowledgeSource.workspace_id == principal.workspace_id,
        )
    )
    if not source:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    object_key = source.object_key
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
            "objectKey": object_key,
            "extractionKey": source.extraction_key,
        },
    )
    await session.commit()
    return Response(status_code=204)


def _size_label(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


@router.get("/agents/{agent_id}/facts", response_model=list[FactOut])
async def list_facts(
    agent_id: UUID,
    principal: KnowledgeViewPrincipal,
    session: DB,
    fact_status: FactStatus | None = None,
) -> list[KnowledgeFact]:
    await scoped_agent(session, principal.tenant_id, agent_id, workspace_id=principal.workspace_id)
    query = select(KnowledgeFact).where(
        KnowledgeFact.tenant_id == principal.tenant_id,
        KnowledgeFact.workspace_id == principal.workspace_id,
        KnowledgeFact.agent_id == agent_id,
    )
    if fact_status:
        query = query.where(KnowledgeFact.status == fact_status)
    return list((await session.scalars(query.order_by(KnowledgeFact.updated_at.desc()))).all())


@router.post("/agents/{agent_id}/facts", response_model=FactOut, status_code=201)
async def create_fact(
    agent_id: UUID, payload: FactCreate, principal: KnowledgeManagePrincipal, session: DB
) -> KnowledgeFact:
    agent = await scoped_agent(session, principal.tenant_id, agent_id, workspace_id=principal.workspace_id)
    vector = await nvidia_adapter.embed_query(f"{payload.question}\n{payload.answer}")
    fact = KnowledgeFact(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=agent_id,
        question=payload.question.strip(),
        answer=payload.answer.strip(),
        status=payload.status,
        priority=payload.priority,
        revision=agent.published_knowledge_revision,
        embedding_model=get_settings().nvidia_embedding_model,
        embedding=vector,
        approved_by=principal.user_id if payload.status == FactStatus.APPROVED else None,
        approved_at=datetime.now(UTC) if payload.status == FactStatus.APPROVED else None,
    )
    session.add(fact)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_fact",
        aggregate_id=fact.id,
        event_type="knowledge.fact.changed.v1",
        payload={"factId": str(fact.id), "agentId": str(agent_id), "status": fact.status.value},
    )
    await session.commit()
    await session.refresh(fact)
    return fact


async def _scoped_fact(
    fact_id: UUID,
    *,
    principal: Principal,
    session: AsyncSession,
) -> KnowledgeFact:
    fact = await session.scalar(
        select(KnowledgeFact).where(
            KnowledgeFact.id == fact_id,
            KnowledgeFact.tenant_id == principal.tenant_id,
            KnowledgeFact.workspace_id == principal.workspace_id,
        )
    )
    if fact is None:
        raise HTTPException(status_code=404, detail="Knowledge fact not found")
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        fact.agent_id,
        workspace_id=principal.workspace_id,
    )
    await require_education_agent(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent=agent,
    )
    return fact


@router.get(
    "/facts/{fact_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def get_fact_education_scopes(
    fact_id: UUID,
    principal: KnowledgeViewPrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    fact = await _scoped_fact(fact_id, principal=principal, session=session)
    return list(
        await list_fact_scopes(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent_id=fact.agent_id,
            fact_id=fact.id,
        )
    )


@router.put(
    "/facts/{fact_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def set_fact_education_scopes(
    fact_id: UUID,
    payload: EducationKnowledgeScopeReplace,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    fact = await _scoped_fact(fact_id, principal=principal, session=session)
    scopes = await replace_fact_scopes(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=fact.agent_id,
        fact_id=fact.id,
        pairs=payload.scopes,
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_fact",
        aggregate_id=fact.id,
        event_type="education.knowledge.scope.updated.v1",
        payload={
            "factId": str(fact.id),
            "agentId": str(fact.agent_id),
            "scopes": [{"courseId": str(item.course_id), "batchId": str(item.batch_id)} for item in scopes],
        },
    )
    await session.commit()
    return list(scopes)


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def update_fact(
    fact_id: UUID, payload: FactPatch, principal: KnowledgeManagePrincipal, session: DB
) -> KnowledgeFact:
    fact = await session.scalar(
        select(KnowledgeFact).where(
            KnowledgeFact.id == fact_id,
            KnowledgeFact.tenant_id == principal.tenant_id,
            KnowledgeFact.workspace_id == principal.workspace_id,
        )
    )
    if not fact:
        raise HTTPException(status_code=404, detail="Knowledge fact not found")
    patch = payload.model_dump(exclude_unset=True)
    for name, value in patch.items():
        setattr(fact, name, value)
    if "status" in patch and fact.status == FactStatus.APPROVED:
        fact.approved_by = principal.user_id
        fact.approved_at = datetime.now(UTC)
    if {"question", "answer"} & patch.keys():
        fact.embedding = await nvidia_adapter.embed_query(f"{fact.question}\n{fact.answer}")
        fact.embedding_model = get_settings().nvidia_embedding_model
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_fact",
        aggregate_id=fact.id,
        event_type="knowledge.fact.changed.v1",
        payload={"factId": str(fact.id), "agentId": str(fact.agent_id), "status": fact.status.value},
    )
    await session.commit()
    await session.refresh(fact)
    return fact


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: UUID, principal: KnowledgeViewPrincipal, session: DB) -> JobOut:
    job = await session.scalar(
        select(IngestionJob).where(
            IngestionJob.id == job_id,
            IngestionJob.tenant_id == principal.tenant_id,
            IngestionJob.workspace_id == principal.workspace_id,
        )
    )
    if not job:
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
