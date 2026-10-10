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
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
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
from northstar_api.website_cms_models import (
    WebsiteAudit, WebsitePage, WebsiteRevision, WebsiteSiteMenu,
    WebsiteSiteMenuAudit, WebsiteSiteMenuRevision,
    WebsiteRedirect, WebsiteRedirectAudit,
)

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


class SiteMenuItem(BaseModel):
    """Stable, text-only navigation item targeting another published CMS page."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=80)
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    @field_validator("label")
    @classmethod
    def validate_label(cls, label: str) -> str:
        if not label.strip():
            raise ValueError("Navigation label cannot be blank")
        return label.strip()


class SiteMenuDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[SiteMenuItem, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def enforce_unique_items(self) -> "SiteMenuDocument":
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("Navigation item IDs must be unique")
        if len({item.slug for item in self.items}) != len(self.items):
            raise ValueError("Each page may appear only once in the primary menu")
        return self


class SiteMenuSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    document: SiteMenuDocument


class SiteMenuPublish(VersionGuard):
    pass


class RedirectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    target_slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    status_code: Literal[307, 308] = 308


class RedirectEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    target_slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    status_code: Literal[307, 308]
    enabled: bool


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


async def _lock_public_route_namespace(session: DBSession, principal: Principal) -> None:
    """Serialize CMS page and redirect claims on the same workspace URL namespace.

    PostgreSQL FOR UPDATE prevents a concurrent page create and redirect create
    from reserving the same slug in separate tables.
    """
    workspace = await session.scalar(select(Workspace.id).where(
        Workspace.id == _scope(principal),
        Workspace.tenant_id == principal.tenant_id,
        Workspace.status == WorkspaceStatus.ACTIVE,
    ).with_for_update())
    if workspace is None:
        raise HTTPException(404, "Workspace unavailable")


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
    await _lock_public_route_namespace(session, principal)
    # The public resolver must never ambiguously choose between a CMS page and a redirect.
    reserved = await session.scalar(select(WebsiteRedirect.id).where(
        WebsiteRedirect.tenant_id == principal.tenant_id,
        WebsiteRedirect.workspace_id == _scope(principal),
        WebsiteRedirect.source_slug == document.slug,
    ))
    if reserved is not None:
        raise HTTPException(409, "Page URL is reserved by a redirect rule")
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


def _menu_info(menu: WebsiteSiteMenu | None, document: SiteMenuDocument) -> dict[str, Any]:
    return {
        "draftVersion": menu.draft_version if menu is not None else 0,
        "publishedVersion": menu.published_version if menu is not None else None,
        "document": document.model_dump(mode="json"),
    }


async def _workspace_menu(session: DBSession, workspace_id: UUID, tenant_id: UUID) -> WebsiteSiteMenu | None:
    return await session.scalar(select(WebsiteSiteMenu).where(
        WebsiteSiteMenu.workspace_id == workspace_id,
        WebsiteSiteMenu.tenant_id == tenant_id,
    ))


async def _menu_revision(
    session: DBSession, menu: WebsiteSiteMenu, version: int,
) -> WebsiteSiteMenuRevision:
    revision = await session.scalar(
        select(WebsiteSiteMenuRevision).where(
            WebsiteSiteMenuRevision.menu_id == menu.id,
            WebsiteSiteMenuRevision.version == version,
        )
    )
    if revision is None:
        raise HTTPException(409, "Menu revision unavailable")
    return revision


async def _published_menu_links(
    session: DBSession, workspace_id: UUID, tenant_id: UUID,
) -> tuple[tuple[str, str], ...]:
    menu = await _workspace_menu(session, workspace_id, tenant_id)
    if menu is None or menu.published_version is None:
        return ()
    revision = await _menu_revision(session, menu, menu.published_version)
    doc = SiteMenuDocument.model_validate(revision.document_json)
    if not doc.items:
        return ()
    slugs = [item.slug for item in doc.items]
    public_slugs = set((await session.scalars(select(WebsitePage.slug).where(
        WebsitePage.tenant_id == tenant_id,
        WebsitePage.workspace_id == workspace_id,
        WebsitePage.slug.in_(slugs),
        WebsitePage.published_version.is_not(None),
    ))).all())
    prefix = get_settings().app_api_prefix.rstrip("/")
    return tuple(
        (item.label, f"{prefix}/site-cms/public/{workspace_id}/{item.slug}")
        for item in doc.items if item.slug in public_slugs
    )


def _redirect_info(rule: WebsiteRedirect) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "sourceSlug": rule.source_slug,
        "targetSlug": rule.target_slug,
        "statusCode": rule.status_code,
        "enabled": rule.enabled,
        "version": rule.version,
    }


async def _redirect_target_is_public(
    session: DBSession, workspace_id: UUID, tenant_id: UUID, slug: str,
) -> bool:
    target = await session.scalar(select(WebsitePage.id).where(
        WebsitePage.tenant_id == tenant_id,
        WebsitePage.workspace_id == workspace_id,
        WebsitePage.slug == slug,
        WebsitePage.published_version.is_not(None),
    ))
    return target is not None


async def _ensure_redirect_target(
    session: DBSession, tenant_id: UUID, workspace_id: UUID,
    source: str, target: str,
) -> None:
    if source == target:
        raise HTTPException(422, "Redirect target must differ from the source URL")
    if not await _redirect_target_is_public(session, workspace_id, tenant_id, target):
        raise HTTPException(409, "Redirect destination must be a published site page")


@router.get("/redirects")
async def list_site_redirects(
    principal: CmsAdmin, session: DBSession, response: Response,
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "private, no-store"
    rows = (await session.scalars(select(WebsiteRedirect).where(
        WebsiteRedirect.tenant_id == principal.tenant_id,
        WebsiteRedirect.workspace_id == _scope(principal),
    ).order_by(WebsiteRedirect.source_slug))).all()
    return [_redirect_info(row) for row in rows]


@router.post("/redirects", status_code=201)
async def create_site_redirect(
    payload: RedirectCreate, principal: CmsAdmin, session: DBSession, response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    workspace_id = _scope(principal)
    await _lock_public_route_namespace(session, principal)
    await _ensure_redirect_target(
        session, principal.tenant_id, workspace_id,
        payload.source_slug, payload.target_slug,
    )
    existing_page = await session.scalar(select(WebsitePage).where(
        WebsitePage.tenant_id == principal.tenant_id,
        WebsitePage.workspace_id == workspace_id,
        WebsitePage.slug == payload.source_slug,
    ))
    if existing_page is not None and (
        existing_page.published_version is not None or existing_page.status != "archived"
    ):
        raise HTTPException(409, "Only unused or archived page URLs can be redirected")
    row = WebsiteRedirect(
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        source_slug=payload.source_slug,
        target_slug=payload.target_slug,
        status_code=payload.status_code,
        enabled=True,
        version=1,
    )
    session.add(row)
    try:
        await session.flush()
        session.add(WebsiteRedirectAudit(
            redirect_id=row.id, actor_id=principal.user_id,
            action="create", version=1,
            details_json=_redirect_info(row),
        ))
        event = enqueue_event(
            session, tenant_id=principal.tenant_id,
            aggregate_type="website_redirect", aggregate_id=row.id,
            event_type="website.redirect.created",
            payload={
                "workspaceId": str(workspace_id), "sourceSlug": row.source_slug,
                "targetSlug": row.target_slug, "version": row.version,
            },
        )
        event.workspace_id = workspace_id
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Redirect source is already reserved") from None
    return _redirect_info(row)


@router.put("/redirects/{redirect_id}")
async def update_site_redirect(
    redirect_id: UUID, payload: RedirectEdit,
    principal: CmsAdmin, session: DBSession, response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    workspace_id = _scope(principal)
    rule = await session.scalar(select(WebsiteRedirect).where(
        WebsiteRedirect.id == redirect_id,
        WebsiteRedirect.tenant_id == principal.tenant_id,
        WebsiteRedirect.workspace_id == workspace_id,
    ))
    if rule is None:
        raise HTTPException(404, "Redirect rule not found")
    if payload.expected_version != rule.version:
        raise HTTPException(409, "Redirect version changed; reload before saving")
    if payload.enabled:
        await _ensure_redirect_target(
            session, principal.tenant_id, workspace_id,
            rule.source_slug, payload.target_slug,
        )
    changed = await session.execute(update(WebsiteRedirect).where(
        WebsiteRedirect.id == rule.id,
        WebsiteRedirect.tenant_id == principal.tenant_id,
        WebsiteRedirect.workspace_id == workspace_id,
        WebsiteRedirect.version == payload.expected_version,
    ).values(
        target_slug=payload.target_slug,
        status_code=payload.status_code,
        enabled=payload.enabled,
        version=payload.expected_version + 1,
        updated_at=datetime.now(UTC),
    ))
    if changed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Redirect rule changed concurrently")
    rule.target_slug = payload.target_slug
    rule.status_code = payload.status_code
    rule.enabled = payload.enabled
    rule.version = payload.expected_version + 1
    session.add(WebsiteRedirectAudit(
        redirect_id=rule.id, actor_id=principal.user_id,
        action="update" if payload.enabled else "disable",
        version=rule.version, details_json=_redirect_info(rule),
    ))
    event = enqueue_event(
        session, tenant_id=principal.tenant_id,
        aggregate_type="website_redirect", aggregate_id=rule.id,
        event_type="website.redirect.updated",
        payload={
            "workspaceId": str(workspace_id), "sourceSlug": rule.source_slug,
            "targetSlug": rule.target_slug, "statusCode": rule.status_code,
            "enabled": rule.enabled, "version": rule.version,
        },
    )
    event.workspace_id = workspace_id
    await session.commit()
    return _redirect_info(rule)


@router.get("/menu")
async def get_site_menu(
    principal: CmsAdmin, session: DBSession, response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    menu = await _workspace_menu(session, _scope(principal), principal.tenant_id)
    if menu is None:
        return _menu_info(None, SiteMenuDocument())
    revision = await _menu_revision(session, menu, menu.draft_version)
    return _menu_info(menu, SiteMenuDocument.model_validate(revision.document_json))


@router.put("/menu")
async def save_site_menu(
    payload: SiteMenuSave, principal: CmsAdmin, session: DBSession, response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    workspace_id = _scope(principal)
    menu = await _workspace_menu(session, workspace_id, principal.tenant_id)
    document = payload.document.model_dump(mode="json")
    if menu is None:
        if payload.expected_version != 0:
            raise HTTPException(409, "Site menu was created by another editor")
        menu = WebsiteSiteMenu(
            tenant_id=principal.tenant_id, workspace_id=workspace_id,
            draft_version=1, published_version=None,
        )
        session.add(menu)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(409, "Site menu was created concurrently") from None
        action = "create"
    else:
        if payload.expected_version != menu.draft_version:
            raise HTTPException(409, "Site menu was modified by another editor")
        changed = await session.execute(
            update(WebsiteSiteMenu).where(
                WebsiteSiteMenu.id == menu.id,
                WebsiteSiteMenu.tenant_id == principal.tenant_id,
                WebsiteSiteMenu.workspace_id == workspace_id,
                WebsiteSiteMenu.draft_version == payload.expected_version,
            ).values(
                draft_version=payload.expected_version + 1,
                updated_at=datetime.now(UTC),
            )
        )
        if changed.rowcount != 1:
            await session.rollback()
            raise HTTPException(409, "Site menu was modified concurrently")
        menu.draft_version = payload.expected_version + 1
        action = "edit"
    session.add(WebsiteSiteMenuRevision(
        menu_id=menu.id, version=menu.draft_version,
        document_json=document, created_by=principal.user_id,
    ))
    session.add(WebsiteSiteMenuAudit(
        menu_id=menu.id, actor_id=principal.user_id,
        action=action, revision_version=menu.draft_version,
    ))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Menu version conflict") from None
    return _menu_info(menu, payload.document)


@router.post("/menu/publish")
async def publish_site_menu(
    payload: SiteMenuPublish, principal: CmsAdmin, session: DBSession, response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    workspace_id = _scope(principal)
    menu = await _workspace_menu(session, workspace_id, principal.tenant_id)
    if menu is None or menu.draft_version != payload.expected_version:
        raise HTTPException(409, "Menu version changed; reload before publishing")
    revision = await _menu_revision(session, menu, menu.draft_version)
    document = SiteMenuDocument.model_validate(revision.document_json)
    slugs = {item.slug for item in document.items}
    if slugs:
        published_slugs = set((await session.scalars(select(WebsitePage.slug).where(
            WebsitePage.tenant_id == principal.tenant_id,
            WebsitePage.workspace_id == workspace_id,
            WebsitePage.slug.in_(slugs),
            WebsitePage.published_version.is_not(None),
        ))).all())
        missing = sorted(slugs - published_slugs)
        if missing:
            raise HTTPException(
                409, "Publish the linked pages first: " + ", ".join(missing[:10]),
            )
    if menu.published_version == menu.draft_version:
        return _menu_info(menu, document)  # Idempotent, without duplicate audit or outbox effects.
    updated = await session.execute(
        update(WebsiteSiteMenu).where(
            WebsiteSiteMenu.id == menu.id,
            WebsiteSiteMenu.draft_version == payload.expected_version,
            WebsiteSiteMenu.published_version.is_distinct_from(payload.expected_version),
        ).values(published_version=menu.draft_version, updated_at=datetime.now(UTC))
    )
    if updated.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Menu publication changed concurrently")
    menu.published_version = menu.draft_version
    session.add(WebsiteSiteMenuAudit(
        menu_id=menu.id, actor_id=principal.user_id,
        action="publish", revision_version=menu.draft_version,
    ))
    event = enqueue_event(
        session, tenant_id=principal.tenant_id,
        aggregate_type="website_menu", aggregate_id=menu.id,
        event_type="website.menu.published",
        payload={"workspaceId": str(workspace_id), "version": menu.draft_version},
    )
    event.workspace_id = workspace_id
    await session.commit()
    return _menu_info(menu, document)


@router.get("/menu/revisions")
async def site_menu_revision_history(
    principal: CmsAdmin, session: DBSession, response: Response,
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "private, no-store"
    menu = await _workspace_menu(session, _scope(principal), principal.tenant_id)
    if menu is None:
        return []
    rows = (await session.scalars(select(WebsiteSiteMenuRevision).where(
        WebsiteSiteMenuRevision.menu_id == menu.id,
    ).order_by(WebsiteSiteMenuRevision.version.desc()))).all()
    return [{
        "version": row.version, "createdAt": row.created_at.isoformat(),
        "isPublished": row.version == menu.published_version,
    } for row in rows]


@router.post("/menu/restore/{version}")
async def restore_site_menu(
    version: int, payload: SiteMenuPublish,
    principal: CmsAdmin, session: DBSession, response: Response,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "private, no-store"
    menu = await _workspace_menu(session, _scope(principal), principal.tenant_id)
    if menu is None or menu.draft_version != payload.expected_version or version < 1:
        raise HTTPException(409, "Menu version changed; reload before restoring")
    original = await _menu_revision(session, menu, version)
    copied = SiteMenuDocument.model_validate(original.document_json)
    changed = await session.execute(update(WebsiteSiteMenu).where(
        WebsiteSiteMenu.id == menu.id,
        WebsiteSiteMenu.draft_version == payload.expected_version,
    ).values(draft_version=payload.expected_version + 1, updated_at=datetime.now(UTC)))
    if changed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Menu version changed concurrently")
    menu.draft_version = payload.expected_version + 1
    session.add(WebsiteSiteMenuRevision(
        menu_id=menu.id, version=menu.draft_version,
        document_json=copied.model_dump(mode="json"), created_by=principal.user_id,
    ))
    session.add(WebsiteSiteMenuAudit(
        menu_id=menu.id, actor_id=principal.user_id,
        action="restore", revision_version=menu.draft_version,
    ))
    await session.commit()
    return _menu_info(menu, copied)


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
    if action not in {
        EditorialAction.SUBMIT, EditorialAction.APPROVE, EditorialAction.PUBLISH,
        EditorialAction.ARCHIVE, EditorialAction.RESTORE_DRAFT,
        EditorialAction.REQUEST_CHANGES,
    }:
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
            **(
                {"published_version": page.draft_version}
                if action == EditorialAction.PUBLISH else
                {"published_version": None} if action == EditorialAction.ARCHIVE else {}
            ),
            updated_at=datetime.now(UTC),
        )
    )
    if changed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Page state changed concurrently")
    page.status = new_state.value
    if action == EditorialAction.PUBLISH:
        page.published_version = page.draft_version
    if action == EditorialAction.ARCHIVE:
        # Archival disables public serving without deleting any source revision.
        page.published_version = None
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
    if action == EditorialAction.ARCHIVE:
        event = enqueue_event(
            session, tenant_id=principal.tenant_id, aggregate_type="website_page",
            aggregate_id=page.id, event_type="website.page.unpublished",
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
async def public_page(workspace_id: UUID, slug: str, session: DBSession) -> Response:
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
        rule = await session.scalar(select(WebsiteRedirect).where(
            WebsiteRedirect.tenant_id == workspace.tenant_id,
            WebsiteRedirect.workspace_id == workspace_id,
            WebsiteRedirect.source_slug == slug,
            WebsiteRedirect.enabled.is_(True),
        ))
        if rule is not None and await _redirect_target_is_public(
            session, workspace_id, workspace.tenant_id, rule.target_slug,
        ):
            prefix = get_settings().app_api_prefix.rstrip("/")
            return RedirectResponse(
                url=f"{prefix}/site-cms/public/{workspace_id}/{rule.target_slug}",
                status_code=rule.status_code,
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
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
            navigation=await _published_menu_links(session, workspace_id, workspace.tenant_id),
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
