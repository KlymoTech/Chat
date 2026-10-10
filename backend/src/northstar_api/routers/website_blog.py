"""Public, tenant-isolated website resource index.

Only published immutable revisions with explicit article metadata can appear.
Drafts, unapproved claims and unpublished revisions never enter public listings.
"""
from __future__ import annotations

from html import escape
from math import ceil
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from northstar_api.dependencies import DBSession
from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.services.website_builder_document import BuilderPageDocument
from northstar_api.website_cms_models import WebsitePage, WebsiteRevision

router = APIRouter(prefix="/site-blog", tags=["site-blog"])

_INDEX_CSS = (
    "body{margin:0;color:#172033;background:#f8fafc;font:16px/1.6 system-ui,sans-serif}"
    ".wrap{max-width:1080px;margin:auto;padding:30px 20px 80px}"
    "h1{font-size:clamp(2rem,4vw,3.5rem);line-height:1.12}"
    "a{color:#1d4ed8}a:focus-visible{outline:3px solid #d97706;outline-offset:3px}"
    ".articles{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:18px}"
    "article{background:white;padding:22px;border:1px solid #cbd5e1;border-radius:14px}"
    "article h2{font-size:1.3rem;line-height:1.3}"
    "small{color:#475569}nav{display:flex;gap:16px;margin-top:26px}"
    ".skip{position:absolute;left:-9999px}.skip:focus{left:12px}"
)


async def _published_articles(workspace_id: UUID, session: DBSession) -> list[dict[str, str]]:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id, Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    if workspace is None:
        raise HTTPException(404, "Website not found")
    rows = (await session.execute(
        select(WebsitePage, WebsiteRevision).join(
            WebsiteRevision,
            (WebsiteRevision.page_id == WebsitePage.id)
            & (WebsiteRevision.version == WebsitePage.published_version),
        ).where(
            WebsitePage.tenant_id == workspace.tenant_id,
            WebsitePage.workspace_id == workspace_id,
            WebsitePage.published_version.is_not(None),
        ).order_by(WebsitePage.slug)
    )).all()
    articles = []
    for page, revision in rows:
        document = BuilderPageDocument.model_validate(revision.document_json)
        if document.content_type != "article" or document.blog is None:
            continue
        articles.append({
            "slug": document.slug,
            "title": document.title,
            "author": document.blog.author,
            "category": document.blog.category,
            "summary": document.blog.summary,
            "reviewer": document.blog.reviewer or "",
            "locale": document.blog.locale,
        })
    return articles


def _filter_articles(items: list[dict[str, str]], category: str | None) -> list[dict[str, str]]:
    if category is None:
        return items
    category = category.casefold()
    return [item for item in items if item["category"].casefold() == category]


@router.get("/{workspace_id}/articles")
async def published_articles(
    workspace_id: UUID, session: DBSession,
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    per_page: Annotated[int, Query(ge=1, le=24)] = 12,
    category: Annotated[str | None, Query(max_length=80)] = None,
) -> dict[str, Any]:
    all_articles = _filter_articles(await _published_articles(workspace_id, session), category)
    start = (page - 1) * per_page
    return {
        "items": all_articles[start:start + per_page],
        "page": page,
        "perPage": per_page,
        "total": len(all_articles),
        "totalPages": ceil(len(all_articles) / per_page),
    }


@router.get("/{workspace_id}", response_class=HTMLResponse)
async def public_blog_index(workspace_id: UUID, session: DBSession) -> HTMLResponse:
    """Server-rendered resource landing page that requires no browser JavaScript."""
    articles = await _published_articles(workspace_id, session)
    cards = "".join(
        '<article><small>' + escape(item["category"]) + ' · ' + escape(item["author"])
        + '</small><h2><a href="/api/v1/site-cms/public/' + str(workspace_id)
        + '/' + escape(item["slug"], quote=True) + '">'
        + escape(item["title"]) + '</a></h2><p>'
        + escape(item["summary"]) + '</p></article>'
        for item in articles[:24]
    )
    if not cards:
        cards = "<p>No articles have been published yet.</p>"
    body = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        '<title>Articles and resources</title><style>' + _INDEX_CSS
        + '</style></head><body><a class="skip" href="#articles">Skip to articles</a>'
        '<main class="wrap" id="articles"><h1>Articles and resources</h1>'
        '<div class="articles">' + cards + '</div></main></body></html>'
    )
    import base64
    import hashlib
    digest = base64.b64encode(hashlib.sha256(_INDEX_CSS.encode()).digest()).decode("ascii")
    return HTMLResponse(
        content=body,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'sha256-" + digest
                + "'; base-uri 'none'; frame-ancestors 'self'"
            ),
        },
    )
