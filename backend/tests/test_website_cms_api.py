"""API integration: private drafts, immutable public snapshots and tenant-scoped authoring."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.website_cms_models import WebsiteAudit, WebsiteRevision


def page_document(slug: str, text: str) -> dict:
    return {
        "schema_version": 1, "slug": slug, "title": "CMS test page",
        "nodes": [{"id": "hero", "kind": "section", "children": [
            {"id": "heading", "kind": "heading", "text": text},
            {"id": "cta", "kind": "button", "text": "Read more", "url": "/contact"},
        ]}],
    }


async def test_cms_draft_review_publish_and_revision_isolation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    scope = await client.get("/api/v1/workspace", headers=auth_headers)
    assert scope.status_code == 200, scope.text
    workspace_id = scope.json()["id"]
    slug = "cms-test-" + uuid4().hex[:12]
    draft = page_document(slug, "<unsafe>Hello</unsafe>")

    unauthenticated = await client.get("/api/v1/site-cms/pages")
    assert unauthenticated.status_code == 401

    created = await client.post("/api/v1/site-cms/pages", headers=auth_headers, json=draft)
    assert created.status_code == 201, created.text
    data = created.json()
    page_id = data["id"]
    assert data["status"] == "draft"
    assert data["draftVersion"] == 1
    assert data["publishedVersion"] is None

    public_path = "/api/v1/site-cms/public/" + workspace_id + "/" + slug
    before = await client.get(public_path)
    assert before.status_code == 404
    private = await client.get("/api/v1/site-cms/pages", headers=auth_headers)
    assert private.status_code == 200
    assert any(item["id"] == page_id for item in private.json())

    premature = await client.post(
        "/api/v1/site-cms/pages/" + page_id + "/publish", headers=auth_headers,
    )
    assert premature.status_code == 409

    for action, expected in (("submit", "in_review"), ("approve", "approved"), ("publish", "published")):
        result = await client.post(
            "/api/v1/site-cms/pages/" + page_id + "/" + action, headers=auth_headers,
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == expected

    published = await client.get(public_path)
    assert published.status_code == 200, published.text
    assert "<unsafe>" not in published.text
    assert "&lt;unsafe&gt;Hello&lt;/unsafe&gt;" in published.text
    assert published.headers["cache-control"] == "no-store"
    assert published.headers["x-content-type-options"] == "nosniff"

    revision = page_document(slug, "Updated version")
    changed = await client.put("/api/v1/site-cms/pages/" + page_id, headers=auth_headers,
                               json={"expected_version": 1, "document": revision})
    assert changed.status_code == 200, changed.text
    assert changed.json()["draftVersion"] == 2
    assert changed.json()["publishedVersion"] == 1
    assert changed.json()["status"] == "draft"

    # The public page continues to serve the *last published immutable version*.
    old_live = await client.get(public_path)
    assert old_live.status_code == 200
    assert "Updated version" not in old_live.text
    assert "&lt;unsafe&gt;" in old_live.text

    stale_write = await client.put("/api/v1/site-cms/pages/" + page_id, headers=auth_headers,
                                   json={"expected_version": 1, "document": revision})
    assert stale_write.status_code == 409

    duplicate = await client.post("/api/v1/site-cms/pages", headers=auth_headers, json=draft)
    assert duplicate.status_code == 409

    unsafe = page_document("unsafe-" + uuid4().hex[:12], "Hello")
    unsafe["nodes"][0]["children"][1]["url"] = "javascript:alert(1)"
    refused = await client.post("/api/v1/site-cms/pages", headers=auth_headers, json=unsafe)
    assert refused.status_code == 422

    async with SessionFactory() as session:
        count = await session.scalar(
            select(func.count()).select_from(WebsiteRevision).where(WebsiteRevision.page_id == UUID(page_id))
        )
        audit_count = await session.scalar(
            select(func.count()).select_from(WebsiteAudit).where(WebsiteAudit.page_id == UUID(page_id))
        )
    assert count == 2
    assert audit_count == 5
