from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import structlog
from fastapi import HTTPException, Response
from pydantic import Field
from sqlalchemy import select

from northstar_api.config import get_settings
from northstar_api.education_knowledge_lifecycle import (
    EducationSourceVersion,
)
from northstar_api.education_knowledge_schemas import (
    EducationKnowledgeScopeRef,
)
from northstar_api.education_knowledge_scope import EducationKnowledgeScope
from northstar_api.models import (
    IngestionJob,
    JobStatus,
    KnowledgeKind,
    KnowledgeSource,
    KnowledgeStatus,
)
from northstar_api.modules.knowledge.ingestion import ingest_source_async
from northstar_api.routers import knowledge_assignments as _knowledge_assignments  # noqa: F401
from northstar_api.routers import knowledge_extraction_area as _knowledge_extraction_area  # noqa: F401
from northstar_api.routers import knowledge_facts as _knowledge_facts  # noqa: F401
from northstar_api.routers import knowledge_lifecycle as _knowledge_lifecycle  # noqa: F401
from northstar_api.routers import knowledge_releases as _knowledge_releases  # noqa: F401
from northstar_api.routers import knowledge_source_scopes as _knowledge_source_scopes  # noqa: F401
from northstar_api.routers.agents import scoped_agent
from northstar_api.routers.knowledge_routes import (
    DB,
    KnowledgeManagePrincipal,
    KnowledgeViewPrincipal,
    router,
)
from northstar_api.routers.knowledge_support import (
    load_extraction as _load_extraction,
)
from northstar_api.routers.knowledge_support import (
    review_source as _review_source,
)
from northstar_api.routers.knowledge_support import (
    size_label as _size_label,
)
from northstar_api.routers.knowledge_support import (
    source_response,
)
from northstar_api.schemas import (
    APIModel,
    KnowledgeCreate,
    KnowledgeOut,
    UploadPresignOut,
    UploadPresignRequest,
)
from northstar_api.services.education_knowledge import (
    require_education_agent,
    validate_scope_pairs,
)
from northstar_api.services.extraction_review import apply_review
from northstar_api.services.extraction_schema import Reading
from northstar_api.services.object_store import InvalidUpload, ObjectStoreUnavailable, object_store
from northstar_api.services.outbox import enqueue_event

logger = structlog.get_logger(__name__)


@router.post("/uploads/presign", response_model=UploadPresignOut)
async def presign_upload(
    payload: UploadPresignRequest, principal: KnowledgeManagePrincipal
) -> UploadPresignOut:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Select an authorized workspace")
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
            workspace_id=principal.workspace_id,
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


@router.get("/agents/{agent_id}/knowledge", response_model=list[KnowledgeOut])
async def list_knowledge(
    agent_id: UUID, principal: KnowledgeViewPrincipal, session: DB
) -> list[KnowledgeOut]:
    await scoped_agent(
        session,
        principal.tenant_id,
        agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
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
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    if payload.kind == KnowledgeKind.TEXT and not payload.content:
        raise HTTPException(status_code=422, detail="Text sources require content")
    if payload.kind in (KnowledgeKind.URL, KnowledgeKind.SITEMAP) and not payload.url:
        raise HTTPException(status_code=422, detail="URL and sitemap sources require a URL")
    if payload.kind == KnowledgeKind.FILE and not payload.object_key:
        raise HTTPException(status_code=422, detail="File sources require an uploaded object key")
    if payload.kind == KnowledgeKind.FILE and payload.content is not None:
        raise HTTPException(status_code=422, detail="Uploaded files must pass source extraction and review")
    if payload.object_key and payload.kind != KnowledgeKind.FILE:
        raise HTTPException(status_code=422, detail="Only file sources can reference an uploaded object")
    if payload.simplified_training and payload.education_destination is None:
        raise HTTPException(
            status_code=422,
            detail="Choose the simplified Course this training document belongs to",
        )
    if payload.retrieval_mode == "pgvector" and payload.education_destination is None:
        raise HTTPException(
            status_code=422,
            detail="PGVector retrieval is available only for a Course training document",
        )
    if payload.education_destination is not None and payload.unassigned_inbox:
        raise HTTPException(status_code=422, detail="Choose an Education destination or the unassigned inbox")
    if payload.education_destination is not None:
        await require_education_agent(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent=agent,
        )

    object_key = payload.object_key
    uploaded_checksum: str | None = None
    uploaded_size: int | None = None
    uploaded_version: str | None = None
    if object_key:
        try:
            (
                object_key,
                uploaded_checksum,
                uploaded_size,
                uploaded_version,
            ) = await object_store.promote_staged(
                principal.tenant_id, object_key, workspace_id=principal.workspace_id
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
        object_version_id=uploaded_version,
        checksum=uploaded_checksum or hashlib.sha256(raw_identity.encode()).hexdigest(),
        retrieval_mode=payload.retrieval_mode,
    )
    session.add(source)
    await session.flush()
    source_version = EducationSourceVersion(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        source_id=source.id,
        version=source.revision,
        checksum=source.checksum or "",
        processing_configuration={"pipeline": "existing", "sourceKind": source.kind.value},
        state="processing",
    )
    session.add(source_version)
    await session.flush()
    if payload.education_destination is not None:
        destination = payload.education_destination
        normalized = await validate_scope_pairs(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            pairs=[
                EducationKnowledgeScopeRef(
                    course_id=destination.course_id,
                    curriculum_id=destination.curriculum_id,
                    paper_id=destination.paper_id,
                    batch_id=destination.batch_id,
                    material_type=destination.material_type,
                )
            ],
        )
        selected = normalized[0]
        from northstar_api.education import EducationCourse

        course = await session.scalar(
            select(EducationCourse).where(
                EducationCourse.id == selected.course_id,
                EducationCourse.tenant_id == principal.tenant_id,
                EducationCourse.workspace_id == principal.workspace_id,
            )
        )
        if course is None:
            raise HTTPException(status_code=422, detail="Education destination Course no longer exists")
        if course.simplified_workflow and course.assigned_agent_id != agent.id:
            raise HTTPException(
                status_code=422,
                detail="A simplified Course can only receive training from its assigned Education Agent",
            )
        # One active Course deliberately uses one retrieval mode. This prevents
        # one answer from combining lexical and vector candidates while still
        # letting the same Agent serve different Courses in different modes.
        existing_modes = (
            await session.scalars(
                select(KnowledgeSource.retrieval_mode)
                .join(EducationKnowledgeScope, EducationKnowledgeScope.source_id == KnowledgeSource.id)
                .where(
                    EducationKnowledgeScope.tenant_id == principal.tenant_id,
                    EducationKnowledgeScope.workspace_id == principal.workspace_id,
                    EducationKnowledgeScope.agent_id == agent.id,
                    EducationKnowledgeScope.course_id == selected.course_id,
                    KnowledgeSource.status != KnowledgeStatus.FAILED,
                )
                .distinct()
            )
        ).all()
        normalized_modes = {mode or "lexical" for mode in existing_modes}
        if normalized_modes and normalized_modes != {payload.retrieval_mode}:
            existing_label = "PGVector" if "pgvector" in normalized_modes else "lexical"
            raise HTTPException(
                status_code=422,
                detail=(
                    f"This Course already has {existing_label} retrieval documents. "
                    "Use the same mode for every document in this Course."
                ),
            )
        direct_simplified_course = bool(course.simplified_workflow and course.assigned_agent_id == agent.id)
        now = datetime.now(UTC)
        session.add(
            EducationKnowledgeScope(
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                agent_id=agent.id,
                source_id=source.id,
                source_version_id=source_version.id,
                course_id=selected.course_id,
                curriculum_id=selected.curriculum_id,
                paper_id=selected.paper_id,
                batch_id=selected.batch_id,
                material_type=selected.material_type,
                approval_status="published" if direct_simplified_course else "draft",
                approved_at=now if direct_simplified_course else None,
                published_at=now if direct_simplified_course else None,
                requires_release=not direct_simplified_course,
            )
        )
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
    # commit() expires ORM attributes; source_response() always needs current
    # values regardless of whether ingestion ran inline above.
    await session.refresh(source)
    return source_response(source)


@router.get("/knowledge/{source_id}/extraction")
async def get_extraction(
    source_id: UUID, principal: KnowledgeViewPrincipal, session: DB
) -> dict[str, object]:
    source = await _review_source(source_id, principal, session)
    return (await _load_extraction(source)).record


@router.get("/knowledge/{source_id}/extraction/source-pdf")
async def get_extraction_source_pdf(
    source_id: UUID, principal: KnowledgeViewPrincipal, session: DB
) -> Response:
    """Open the immutable PDF bytes that were used for this extraction revision."""
    source = await _review_source(source_id, principal, session)
    package = await _load_extraction(source)
    original = package.images.get("source/original.pdf")
    if original is None:
        raise HTTPException(status_code=404, detail="The stored source is not a PDF")
    safe_name = source.name.replace('"', "") or "source.pdf"
    return Response(
        content=original,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.get("/knowledge/{source_id}/extraction/text")
async def get_extraction_text(source_id: UUID, principal: KnowledgeViewPrincipal, session: DB) -> Response:
    """Download the canonical extracted text and structured review record."""
    source = await _review_source(source_id, principal, session)
    safe_name = source.name.replace('"', "") or "source"
    return Response(
        content=(await _load_extraction(source)).review_text(),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-extracted.txt"'},
    )


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


@router.get("/knowledge/{source_id}/extraction/regions/{block_id}")
async def get_extraction_region(
    source_id: UUID,
    block_id: str,
    principal: KnowledgeViewPrincipal,
    session: DB,
) -> Response:
    source = await _review_source(source_id, principal, session)
    package = await _load_extraction(source)
    block = next(
        (b for p in package.record["pages"] for b in p.get("blocks", []) if b["id"] == block_id), None
    )
    if not block or block.get("crop") not in package.images:
        raise HTTPException(status_code=404, detail="Source region not found")
    return Response(content=package.images[block["crop"]], media_type="image/png")


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
    all_pages_selected: bool = False
    pages: list[ReviewedPage] = Field(min_length=1, max_length=5_000)
    issue_resolutions: list[IssueResolution] = Field(default_factory=list, max_length=20000)


@router.post("/knowledge/{source_id}/extraction/retry", response_model=KnowledgeOut)
async def retry_extraction(source_id: UUID, principal: KnowledgeManagePrincipal, session: DB) -> KnowledgeOut:
    source = await _review_source(source_id, principal, session)
    # Retrying is intentionally idempotent while a previous request is already
    # being processed. The UI can be left open or a user can click twice; do
    # not turn that normal state transition into a misleading 409 error or
    # enqueue duplicate ingestion jobs.
    if source.status == KnowledgeStatus.PROCESSING:
        return source_response(source)
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
    # A trained file stays editable: saving an edit stores a new reviewed version and retrains it.
    if source.status == KnowledgeStatus.PROCESSING:
        raise HTTPException(
            status_code=409, detail="Training is in progress; edit the file when it shows Training complete"
        )
    if source.status not in {KnowledgeStatus.NEEDS_REVIEW, KnowledgeStatus.READY}:
        raise HTTPException(status_code=409, detail="Source is not awaiting extraction review")
    package = await _load_extraction(source)
    if payload.extraction_revision != source.revision:
        raise HTTPException(status_code=409, detail="Evidence changed; reload before reviewing")
    if payload.all_pages_selected:
        expected_pages = [page["number"] for page in package.record["pages"]]
        submitted_pages = [page.number for page in payload.pages]
        if submitted_pages != expected_pages:
            raise HTTPException(
                status_code=422,
                detail="All-pages review must include every source page in source order",
            )
    settings = get_settings()
    if sum(len(item.selected_text) for item in payload.pages) > settings.knowledge_max_extracted_characters:
        raise HTTPException(status_code=413, detail="Reviewed text exceeds the extraction limit")
    try:
        apply_review(
            package.record,
            [p.model_dump() for p in payload.pages],
            [r.model_dump() for r in payload.issue_resolutions],
            str(principal.user_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    package.refresh()
    pages = package.record["pages"]
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
        await session.refresh(source)
        return source_response(source)
    source.content = "\n\n".join(
        f"===PDF_PAGE:{page['number']}===\n{value}" if page.get("source_unit") == "pdf_page" else value
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
