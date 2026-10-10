"""Public XML sitemap regression tests for verified, immutable website content."""
from __future__ import annotations

from uuid import uuid4
from xml.etree import ElementTree

from httpx import AsyncClient


async def test_sitemap_excludes_drafts_and_uses_last_published_seo_revision(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    info = await client.get("/api/v1/workspace", headers=auth_headers)
    assert info.status_code == 200, info.text
    workspace_id = info.json()["id"]
    slug = "seo-sitemap-" + uuid4().hex[:12]
    canonical = "https://example.org/" + slug
    draft = {
        "schema_version": 1, "slug": slug, "title": "SEO page",
        "seo": {
            "indexable": True, "description": "A useful landing page.",
            "canonical_url": canonical,
        },
        "nodes": [{"id": "hero", "kind": "section", "children": [
            {"id": "heading", "kind": "heading", "text": "SEO page"},
        ]}],
    }
    created = await client.post("/api/v1/site-cms/pages", headers=auth_headers, json=draft)
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    sitemap_url = f"/api/v1/site-discovery/sitemap/{workspace_id}.xml"

    before = await client.get(sitemap_url)
    assert before.status_code == 200, before.text
    assert canonical not in before.text
    assert before.headers["content-type"].startswith("application/xml")

    for action in ("submit", "approve", "publish"):
        response = await client.post(
            f"/api/v1/site-cms/pages/{page_id}/{action}", headers=auth_headers,
        )
        assert response.status_code == 200, response.text

    published = await client.get(sitemap_url)
    assert published.status_code == 200, published.text
    root = ElementTree.fromstring(published.content)
    urls = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
    assert [element.text for element in urls].count(canonical) == 1

    unpublished = {**draft, "seo": {"indexable": False}}
    changed = await client.put(
        f"/api/v1/site-cms/pages/{page_id}",
        headers=auth_headers,
        json={"expected_version": 1, "document": unpublished},
    )
    assert changed.status_code == 200, changed.text
    assert canonical in (await client.get(sitemap_url)).text

    for action in ("submit", "approve", "publish"):
        response = await client.post(
            f"/api/v1/site-cms/pages/{page_id}/{action}", headers=auth_headers,
        )
        assert response.status_code == 200, response.text
    after = await client.get(sitemap_url)
    assert after.status_code == 200
    assert canonical not in after.text


async def test_sitemap_unknown_workspace_is_not_exposed(client: AsyncClient) -> None:
    not_found = await client.get(
        "/api/v1/site-discovery/sitemap/00000000-0000-0000-0000-000000000000.xml"
    )
    assert not_found.status_code == 404
