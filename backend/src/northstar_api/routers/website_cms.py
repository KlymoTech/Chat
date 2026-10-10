"""Tenant-isolated website CMS APIs: editable drafts, approvals and public revisions.

No unpublished version is served without admin authentication. Every mutation
is a database transaction with an actor-attributed audit record.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime
from urllib.parse import quote
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from northstar_api.config import get_settings
from northstar_api.dependencies import DBSession, require_roles
from northstar_api.models import Role, Workspace, WorkspaceStatus
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.website_builder_document import BuilderPageDocument
from northstar_api.services.website_builder_duplicate import duplicate_page_document
from northstar_api.services.website_builder_render import render_page, style_csp_hash
from northstar_api.services.website_cms_lifecycle import EditorialAction, EditorialState, next_editorial_state
from northstar_api.website_cms_models import WebsiteAudit, WebsitePage, WebsiteRevision

router = APIRouter(prefix="/site-cms", tags=["site-cms"])
CmsAdmin = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN))]


class VersionGuard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class PageDuplicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1, max_length=180)


class SiteImportManifest(BaseModel):
    """Allowlisted CMS export format; imported pages never overwrite live content."""

    model_config = ConfigDict(extra="forbid")
    format: Literal["northstar.site-page"]
    version: Literal[1]
    page: BuilderPageDocument
    new_slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    new_title: str = Field(min_length=1, max_length=180)


class PageEdit(VersionGuard):
    document: BuilderPageDocument


def _scope(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=400, detail="Select a workspace to edit website content")
    return principal.workspace_id


def _query(principal: Principal) -> tuple[Any, Any]:
    return (
        WebsitePage.tenant_id == principal.tenant_id,
        WebsitePage.workspace_id == _scope(principal),
    )


async def _get_page(session: DBSession, principal: Principal, page_id: UUID) -> WebsitePage:
    page = await session.scalar(select(WebsitePage).where(WebsitePage.id == page_id, *_query(principal)))
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


async def _revision(session: DBSession, page: WebsitePage, version: int) -> WebsiteRevision:
    record = await session.scalar(
        select(WebsiteRevision).where(WebsiteRevision.page_id == page.id, WebsiteRevision.version == version)
    )
    if record is None:
        raise HTTPException(status_code=409, detail="Page revision is unavailable")
    return record


def _info(page: WebsitePage, document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(page.id),
        "slug": page.slug,
        "title": page.title,
        "status": page.status,
        "draftVersion": page.draft_version,
        "publishedVersion": page.published_version,
        "document": document,
    }


def _audit(page: WebsitePage, principal: Principal, action: str) -> WebsiteAudit:
    return WebsiteAudit(page_id=page.id, actor_id=principal.user_id, action=action, revision_version=page.draft_version)


async def _create_draft_page(
    session: DBSession,
    principal: Principal,
    document: BuilderPageDocument,
    *,
    action: Literal["create", "duplicate", "import"],
) -> dict[str, Any]:
    """One transactional path for all new drafts, revisions, and actor audit rows."""
    page = WebsitePage(
        tenant_id=principal.tenant_id,
        workspace_id=_scope(principal),
        slug=document.slug,
        title=document.title,
        status="draft",
        draft_version=1,
    )
    session.add(page)
    try:
        await session.flush()
        serialized = document.model_dump(mode="json")
        session.add(WebsiteRevision(
            page_id=page.id,
            version=1,
            document_json=serialized,
            created_by=principal.user_id,
        ))
        session.add(_audit(page, principal, action))
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "The destination page URL is already in use") from None
    return _info(page, serialized)


@router.get("/pages")
async def list_pages(principal: CmsAdmin, session: DBSession, response: Response) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "private, no-store"
    pages = (await session.scalars(
        select(WebsitePage).where(*_query(principal)).order_by(WebsitePage.updated_at.desc())
    )).all()
    result = []
    for page in pages:
        revision = await _revision(session, page, page.draft_version)
        result.append(_info(page, revision.document_json))
    return result


@router.post("/pages", status_code=201)
async def create_page(
    payload: BuilderPageDocument, principal: CmsAdmin, session: DBSession,
    response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    return await _create_draft_page(session, principal, payload, action="create")

@router.post("/pages/{page_id}/duplicate", status_code=201)
async def duplicate_page(
    page_id: UUID, payload: PageDuplicate, principal: CmsAdmin,
    session: DBSession, response: Response,
) -> dict[str, Any]:
    """Copy an authorized page into an independent, private draft."""
    response.headers["Cache-Control"] = "private, no-store"
    source = await _get_page(session, principal, page_id)
    original = await _revision(session, source, source.draft_version)
    document = duplicate_page_document(
        BuilderPageDocument.model_validate(original.document_json),
        new_slug=payload.slug, new_title=payload.title,
    )
    return await _create_draft_page(session, principal, document, action="duplicate")

@router.get("/pages/{page_id}/export")
async def export_page_document(
    page_id: UUID, principal: CmsAdmin, session: DBSession, response: Response,
) -> dict[str, Any]:
    """Export a validated current draft as JSON; include no access tokens or private leads."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    page = await _get_page(session, principal, page_id)
    revision = await _revision(session, page, page.draft_version)
    document = BuilderPageDocument.model_validate(revision.document_json)
    return {
        "format": "northstar.site-page",
        "version": 1,
        "page": document.model_dump(mode="json"),
    }


@router.post("/pages/import", status_code=201)
async def import_page_document(
    manifest: SiteImportManifest, principal: CmsAdmin,
    session: DBSession, response: Response,
) -> dict[str, Any]:
    """Import a validated manifest as a new, non-indexable draft."""
    response.headers["Cache-Control"] = "private, no-store"
    copied = duplicate_page_document(
        manifest.page,
        new_slug=manifest.new_slug,
        new_title=manifest.new_title,
    )
    return await _create_draft_page(session, principal, copied, action="import")

@router.put("/pages/{page_id}")
async def save_page(page_id: UUID, payload: PageEdit, principal: CmsAdmin,
                    session: DBSession, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    page = await _get_page(session, principal, page_id)
    if payload.document.slug != page.slug:
        raise HTTPException(422, "Changing a published page URL needs a redirect migration")
    if page.draft_version != payload.expected_version:
        raise HTTPException(409, "Page has changed; reload before saving")
    next_version = page.draft_version + 1
    changed = await session.execute(
        update(WebsitePage)
        .where(WebsitePage.id == page.id, *_query(principal), WebsitePage.draft_version == payload.expected_version)
        .values(
            title=payload.document.title, status="draft",
            draft_version=next_version, updated_at=datetime.now(UTC),
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        await session.rollback()
        raise HTTPException(409, "Page was modified concurrently")
    document = payload.document.model_dump(mode="json")
    page.draft_version = next_version
    page.title = payload.document.title
    page.status = "draft"
    session.add(WebsiteRevision(
        page_id=page.id, version=next_version, document_json=document, created_by=principal.user_id,
    ))
    session.add(_audit(page, principal, "edit"))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Concurrent revision conflict") from None
    return _info(page, document)


@router.post("/pages/{page_id}/{action}")
async def transition_page(page_id: UUID, action: EditorialAction, principal: CmsAdmin,
                          session: DBSession, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    if action not in {EditorialAction.SUBMIT, EditorialAction.APPROVE, EditorialAction.PUBLISH}:
        raise HTTPException(422, "Unsupported CMS action")
    page = await _get_page(session, principal, page_id)
    try:
        new_state = next_editorial_state(EditorialState(page.status), action)
    except ValueError:
        raise HTTPException(409, "Invalid editorial transition") from None
    changed = await session.execute(
        update(WebsitePage)
        .where(
            WebsitePage.id == page.id, *_query(principal),
            WebsitePage.status == page.status, WebsitePage.draft_version == page.draft_version,
        )
        .values(
            status=new_state.value,
            **({"published_version": page.draft_version} if action == EditorialAction.PUBLISH else {}),
            updated_at=datetime.now(UTC),
        )
    )
    if changed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Page state changed concurrently")
    page.status = new_state.value
    if action == EditorialAction.PUBLISH:
        page.published_version = page.draft_version
    session.add(_audit(page, principal, action.value))
    if action == EditorialAction.PUBLISH:
        event = enqueue_event(
            session, tenant_id=principal.tenant_id, aggregate_type="website_page",
            aggregate_id=page.id, event_type="website.page.published",
            payload={
                "pageId": str(page.id), "workspaceId": str(page.workspace_id),
                "slug": page.slug, "revision": page.draft_version,
            },
        )
        event.workspace_id = page.workspace_id
    await session.commit()
    revision = await _revision(session, page, page.draft_version)
    return _info(page, revision.document_json)


@router.get("/public/{workspace_id}/{slug}", response_class=HTMLResponse)
async def public_page(workspace_id: UUID, slug: str, session: DBSession) -> HTMLResponse:
    # Never trust a tenant/workspace identifier or page slug as authorization.
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.status == WorkspaceStatus.ACTIVE)
    )
    if workspace is None:
        raise HTTPException(404, "Published page not found")
    page = await session.scalar(
        select(WebsitePage).where(
            WebsitePage.workspace_id == workspace_id, WebsitePage.tenant_id == workspace.tenant_id,
            WebsitePage.slug == slug, WebsitePage.published_version.is_not(None),
        )
    )
    if page is None or page.published_version is None:
        raise HTTPException(404, "Published page not found")
    revision = await _revision(session, page, page.published_version)
    validated = BuilderPageDocument.model_validate(revision.document_json)
    nonce = secrets.token_urlsafe(18)
    return HTMLResponse(
        content=render_page(
            validated,
            privacy_path=(
                f"/privacy/site/{workspace_id}?returnTo="
                + quote(
                    f"{get_settings().app_api_prefix.rstrip('/')}/site-cms/public/{workspace_id}/{slug}",
                    safe="",
                )
            ),
            analytics_context=(str(workspace_id), get_settings().app_api_prefix),
            analytics_nonce=nonce,
        ),
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": f"default-src 'none'; img-src 'self' https:; script-src 'nonce-{nonce}'; connect-src 'self'; style-src '{style_csp_hash()}'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/pages/{page_id}/revisions")
async def list_revisions(page_id: UUID, principal: CmsAdmin, session: DBSession,
                         response: Response) -> list[dict[str, Any]]:
    """Owner-only immutable revision listing, without exposing drafts to visitors."""
    response.headers["Cache-Control"] = "private, no-store"
    page = await _get_page(session, principal, page_id)
    rows = (await session.scalars(
        select(WebsiteRevision).where(WebsiteRevision.page_id == page.id)
        .order_by(WebsiteRevision.version.desc())
    )).all()
    return [{
        "version": row.version,
        "title": str(row.document_json.get("title", "")),
        "createdAt": row.created_at.isoformat(),
        "isPublished": row.version == page.published_version,
    } for row in rows]


@router.post("/pages/{page_id}/restore/{version}")
async def restore_revision(page_id: UUID, version: int, payload: VersionGuard,
                           principal: CmsAdmin, session: DBSession,
                           response: Response) -> dict[str, Any]:
    """Restore by appending a new draft; never rewrite or discard the old revision."""
    response.headers["Cache-Control"] = "private, no-store"
    page = await _get_page(session, principal, page_id)
    if version < 1 or page.draft_version != payload.expected_version:
        raise HTTPException(409, "Stale draft version or invalid revision")
    original = await _revision(session, page, version)
    document = BuilderPageDocument.model_validate(original.document_json)
    if document.slug != page.slug:
        raise HTTPException(409, "Restored URL differs from this page URL")
    next_version = page.draft_version + 1
    changed = await session.execute(
        update(WebsitePage).where(
            WebsitePage.id == page.id, *_query(principal),
            WebsitePage.draft_version == payload.expected_version,
        ).values(title=document.title, draft_version=next_version, status="draft", updated_at=datetime.now(UTC))
    )
    if changed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Concurrent CMS edit; reload page")
    page.title = document.title
    page.draft_version = next_version
    page.status = "draft"
    session.add(WebsiteRevision(
        page_id=page.id, version=next_version,
        document_json=document.model_dump(mode="json"), created_by=principal.user_id,
    ))
    session.add(_audit(page, principal, "restore"))
    await session.commit()
    return _info(page, document.model_dump(mode="json"))


@router.get("/pages/{page_id}/preview", response_class=HTMLResponse)
async def preview_draft(page_id: UUID, principal: CmsAdmin, session: DBSession) -> HTMLResponse:
    """Authenticated and non-indexable server preview, free of tracking scripts."""
    page = await _get_page(session, principal, page_id)
    revision = await _revision(session, page, page.draft_version)
    content = render_page(BuilderPageDocument.model_validate(revision.document_json))
    return HTMLResponse(
        content,
        headers={
            "Cache-Control": "private, no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "Content-Security-Policy": f"default-src 'none'; img-src 'self' https:; style-src '{style_csp_hash()}'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
            "X-Content-Type-Options": "nosniff",
        },
    )
