"""Fail-closed first-party website event collection and owner reporting.

Browser events are never authoritative leads, purchases or bookings. The event
schema stores no URLs with query strings, contact data or free-form properties.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from northstar_api.dependencies import DBSession, require_roles
from northstar_api.models import Role
from northstar_api.routers.website_consent import (
    _cookie_name, _effective, _global_privacy_control, _latest,
    _same_origin, _subject_hash, _workspace,
)
from northstar_api.security import Principal
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.website_analytics_client import SITE_ANALYTICS_CLIENT_JS
from northstar_api.website_cms_models import WebsitePage
from northstar_api.website_event_models import WebsitePageEvent

router = APIRouter(prefix="/site-analytics", tags=["site-analytics"])
CmsAdmin = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN))]


@router.get("/client.js", include_in_schema=False)
async def analytics_client() -> Response:
    return Response(
        content=SITE_ANALYTICS_CLIENT_JS,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


class BrowserEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    event_id: UUID = Field(alias="eventId")
    event_type: Literal["page_view", "cta_click"] = Field(alias="eventType")
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    block_id: str | None = Field(
        default=None, alias="blockId", max_length=80, pattern=r"^[A-Za-z0-9_-]{1,80}$",
    )


def _respond(status: str) -> dict[str, str]:
    return {"status": status}


@router.post("/{workspace_id}/events", response_model=None)
async def collect_event(
    workspace_id: UUID, event: BrowserEvent, request: Request, response: Response,
    session: DBSession,
) -> dict[str, str] | Response:
    _same_origin(request)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Use JSON for first-party events")
    response.headers["Cache-Control"] = "no-store"
    workspace = await _workspace(session, workspace_id)
    subject = _subject_hash(workspace_id, request.cookies.get(_cookie_name(workspace_id)))
    if subject is None:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    consent = await _latest(session, workspace, subject)
    decision = _effective(consent, gpc=_global_privacy_control(request))
    if decision["analytics"] is not True:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    if event.event_type == "cta_click" and event.block_id is None:
        raise HTTPException(422, "CTA click requires a block identifier")
    if event.event_type == "page_view" and event.block_id is not None:
        raise HTTPException(422, "Page view must not include a block identifier")

    # Unknown/unpublished slugs must never become analytics records.
    page = await session.scalar(select(WebsitePage.id).where(
        WebsitePage.tenant_id == workspace.tenant_id,
        WebsitePage.workspace_id == workspace_id,
        WebsitePage.slug == event.slug,
        WebsitePage.published_version.is_not(None),
    ))
    if page is None:
        raise HTTPException(404, "Published page not found")

    rate = await redis_services.check_rate_limit(
        f"site-analytics:{workspace_id}:{subject}", 180,
        window_seconds=3600, scope="site_analytics",
    )
    if not rate.allowed:
        raise HTTPException(429, "Event limit reached", headers={"Retry-After": str(rate.retry_after)})

    previous = await session.scalar(select(WebsitePageEvent).where(
        WebsitePageEvent.workspace_id == workspace_id,
        WebsitePageEvent.event_id == event.event_id,
    ))
    if previous is not None:
        if (previous.event_type, previous.slug, previous.block_id) != (
            event.event_type, event.slug, event.block_id,
        ):
            raise HTTPException(409, "Event identifier reused for different content")
        return _respond("duplicate")

    stored = WebsitePageEvent(
        tenant_id=workspace.tenant_id, workspace_id=workspace_id,
        event_id=event.event_id, visitor_hash=subject,
        event_type=event.event_type, slug=event.slug,
        block_id=event.block_id, occurred_at=datetime.now(UTC),
    )
    session.add(stored)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        concurrent = await session.scalar(select(WebsitePageEvent).where(
            WebsitePageEvent.workspace_id == workspace_id,
            WebsitePageEvent.event_id == event.event_id,
        ))
        if concurrent is None or (
            concurrent.event_type, concurrent.slug, concurrent.block_id,
        ) != (event.event_type, event.slug, event.block_id):
            raise HTTPException(409, "Event identifier conflict") from None
        return _respond("duplicate")
    return _respond("accepted")


@router.get("/summary")
async def site_analytics_summary(
    principal: CmsAdmin, session: DBSession,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> dict[str, object]:
    if principal.workspace_id is None:
        raise HTTPException(400, "Select a workspace")
    period_start = datetime.now(UTC) - timedelta(days=days)
    scope = (
        WebsitePageEvent.tenant_id == principal.tenant_id,
        WebsitePageEvent.workspace_id == principal.workspace_id,
        WebsitePageEvent.occurred_at >= period_start,
    )
    rows = (await session.execute(
        select(
            WebsitePageEvent.slug, WebsitePageEvent.event_type,
            func.count(WebsitePageEvent.id),
        ).where(*scope).group_by(WebsitePageEvent.slug, WebsitePageEvent.event_type)
    )).all()
    page_views = 0
    cta_clicks = 0
    by_slug: dict[str, int] = {}
    for slug, event_type, count in rows:
        if event_type == "page_view":
            page_views += int(count)
            by_slug[slug] = by_slug.get(slug, 0) + int(count)
        elif event_type == "cta_click":
            cta_clicks += int(count)
    return {
        "days": days,
        "pageViews": page_views,
        "ctaClicks": cta_clicks,
        "pages": [
            {"slug": slug, "pageViews": count}
            for slug, count in sorted(by_slug.items(), key=lambda item: (-item[1], item[0]))
        ][:50],
        "note": "Only browser events submitted under valid analytics consent are counted.",
    }
