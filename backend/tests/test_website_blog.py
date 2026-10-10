"""CMS-backed blog article tests: no draft exposure, revision snapshots and preservation."""
from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient
from pydantic import ValidationError
import pytest

from northstar_api.services.website_builder_document import BuilderPageDocument
from northstar_api.services.website_builder_duplicate import duplicate_page_document


def article(slug: str, *, author: str = "Editorial Team") -> dict:
    return {
        "schema_version": 1, "title": "Article " + slug, "slug": slug,
        "content_type": "article",
        "blog": {
            "author": author,
            "category": "Product updates",
            "summary": "A public editorial summary without private contact data.",
            "locale": "en",
        },
        "nodes": [{"id": "section", "kind": "section", "children": [
            {"id": "heading", "kind": "heading", "text": "Article heading"},
            {"id": "paragraph", "kind": "paragraph", "text": "Readable published article body"},
        ]}],
    }


def test_articles_require_valid_public_metadata():
    payload = article("post")
    payload.pop("blog")
    with pytest.raises(ValidationError):
        BuilderPageDocument.model_validate(payload)

    payload = article("post")
    payload["content_type"] = "page"
    with pytest.raises(ValidationError):
        BuilderPageDocument.model_validate(payload)


def test_duplicate_article_preserves_metadata_without_reusing_seo_identity():
    payload = article("source-article")
    payload["seo"] = {
        "description": "Published article", "canonical_url": "https://example.org/source-article",
        "indexable": True,
    }
    original = BuilderPageDocument.model_validate(payload)
    copied = duplicate_page_document(original, new_slug="copied-article", new_title="Copied article")
    assert copied.content_type == "article"
    assert copied.blog == original.blog
    assert copied.seo.indexable is False
    assert copied.seo.canonical_url is None
    assert copied.nodes[0].id != original.nodes[0].id


async def test_public_blog_index_reads_only_published_immutable_revisions(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    slug = "editorial-" + uuid4().hex[:12]
    path = "/api/v1/site-blog/" + workspace_id
    draft = article(slug)

    saved = await client.post("/api/v1/site-cms/pages", headers=auth_headers, json=draft)
    assert saved.status_code == 201, saved.text
    page_id = saved.json()["id"]

    hidden = await client.get(path + "/articles")
    assert hidden.status_code == 200, hidden.text
    assert slug not in str(hidden.json())
    assert slug not in (await client.get(path)).text

    for action in ("submit", "approve", "publish"):
        completed = await client.post(
            f"/api/v1/site-cms/pages/{page_id}/{action}", headers=auth_headers,
        )
        assert completed.status_code == 200, completed.text

    listing = await client.get(path + "/articles", params={"category": "Product updates"})
    assert listing.status_code == 200, listing.text
    matches = [entry for entry in listing.json()["items"] if entry["slug"] == slug]
    assert len(matches) == 1
    assert matches[0]["author"] == "Editorial Team"
    assert listing.json()["total"] >= 1

    html = await client.get(path)
    assert html.status_code == 200, html.text
    assert slug in html.text
    assert "Editorial Team" in html.text
    assert "no-store" in html.headers["cache-control"]

    edited = article(slug, author="New Author, Not Published")
    changed = await client.put(
        f"/api/v1/site-cms/pages/{page_id}", headers=auth_headers,
        json={"expected_version": 1, "document": edited},
    )
    assert changed.status_code == 200, changed.text
    unchanged = await client.get(path + "/articles")
    before_publish = [item for item in unchanged.json()["items"] if item["slug"] == slug]
    assert before_publish[0]["author"] == "Editorial Team"

    for action in ("submit", "approve", "publish"):
        completed = await client.post(
            f"/api/v1/site-cms/pages/{page_id}/{action}", headers=auth_headers,
        )
        assert completed.status_code == 200, completed.text
    current = await client.get(path + "/articles")
    latest = [item for item in current.json()["items"] if item["slug"] == slug]
    assert latest[0]["author"] == "New Author, Not Published"


async def test_blog_uses_scoped_pagination_and_exposes_no_unknown_workspaces(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    workspace_id = workspace.json()["id"]
    path = "/api/v1/site-blog/" + workspace_id + "/articles"
    response = await client.get(path, params={"per_page": 1, "page": 1})
    assert response.status_code == 200
    assert len(response.json()["items"]) <= 1
    assert response.json()["perPage"] == 1
    assert (await client.get(path, params={"per_page": 0})).status_code == 422
    missing = await client.get(
        "/api/v1/site-blog/00000000-0000-0000-0000-000000000000/articles"
    )
    assert missing.status_code == 404
