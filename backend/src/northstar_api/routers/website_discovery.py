"""Sitemap rendering for only approved, immutable website page revisions."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from northstar_api.dependencies import DBSession
from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.services.website_builder_document import BuilderPageDocument
from northstar_api.website_cms_models import WebsitePage, WebsiteRevision

router = APIRouter(prefix="/site-discovery", tags=["site-discovery"])

_OPEN = '<?xml version="1.0" encoding="UTF-8"?>\n'
_URLSET_OPEN = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
_URLSET_CLOSE = "</urlset>\n"


def _xml_page(canonical_url: str, changed_at: datetime) -> str:
    normalized_time = (
        changed_at.astimezone(UTC) if changed_at.tzinfo is not None
        else changed_at.replace(tzinfo=UTC)
    )
    return (
        "  <url><loc>" + escape(canonical_url) + "</loc>"
        "<lastmod>" + normalized_time.date().isoformat() + "</lastmod></url>\n"
    )


@router.get("/sitemap/{workspace_id}.xml", include_in_schema=False)
async def website_sitemap(workspace_id: UUID, session: DBSession) -> Response:
    """Generate XML exclusively from already published, explicitly indexable revisions."""
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Site not found")
    rows = (await session.execute(
        select(WebsitePage, WebsiteRevision)
        .join(
            WebsiteRevision,
            (WebsiteRevision.page_id == WebsitePage.id)
            & (WebsiteRevision.version == WebsitePage.published_version),
        )
        .where(
            WebsitePage.tenant_id == workspace.tenant_id,
            WebsitePage.workspace_id == workspace_id,
            WebsitePage.published_version.is_not(None),
        )
        .order_by(WebsitePage.slug.asc()),
    )).all()

    urls: set[str] = set()
    entries: list[str] = []
    for page, published_revision in rows:
        document = BuilderPageDocument.model_validate(published_revision.document_json)
        if not document.seo.indexable or not document.seo.canonical_url:
            continue
        if document.seo.canonical_url in urls:
            continue
        urls.add(document.seo.canonical_url)
        entries.append(_xml_page(document.seo.canonical_url, published_revision.created_at))
    return Response(
        content=_OPEN + _URLSET_OPEN + "".join(entries) + _URLSET_CLOSE,
        media_type="application/xml",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
