"""Tenant-isolated website CMS APIs: editable drafts, approvals and public revisions.

No unpublished version is served without admin authentication. Every mutation
is a database transaction with an actor-attributed audit record.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from northstar_api.dependencies import DBSession, require_roles
from northstar_api.models import Role, Workspace, WorkspaceStatus
from northstar_api.security import Principal
from northstar_api.services.website_builder_document import BuilderPageDocument
from northstar_api.services.website_builder_render import render_page
from northstar_api.services.website_cms_lifecycle import EditorialAction, EditorialState, next_editorial_state
from northstar_api.website_cms_models import WebsiteAudit, WebsitePage, WebsiteRevision

router = APIRouter(prefix="/site-cms", tags=["site-cms"])
CmsAdmin = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN))]


class PageEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    document: BuilderPageDocument


def _scope(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=400, detail="Select a workspace to edit website content")
    return principal.workspace_id


def _query(principal: Principal):
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
async def create_page(payload: BuilderPageDocument, principal: CmsAdmin, session: DBSession,
                      response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    page = WebsitePage(
        tenant_id=principal.tenant_id, workspace_id=_scope(principal),
        slug=payload.slug, title=payload.title, status="draft", draft_version=1,
    )
    session.add(page)
    try:
        await session.flush()
        document = payload.model_dump(mode="json")
        session.add(WebsiteRevision(
            page_id=page.id, version=1, document_json=document, created_by=principal.user_id,
        ))
        session.add(_audit(page, principal, "create"))
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "This workspace already has a page with that URL slug") from None
    return _info(page, document)


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
    if changed.rowcount != 1:
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
    return HTMLResponse(
        content=render_page(validated),
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; img-src https:; style-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
            "X-Content-Type-Options": "nosniff",
        },
    )
