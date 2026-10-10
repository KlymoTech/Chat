"""API integration: private drafts, immutable public snapshots and tenant-scoped authoring."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.website_cms_models import WebsiteAudit, WebsiteRevision
from northstar_api.models import OutboxEvent


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
    assert 'Privacy and tracking preferences' in published.text
    assert '/privacy/site/' + workspace_id in published.text
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
        published_events = await session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.aggregate_type == "website_page",
                OutboxEvent.aggregate_id == page_id,
                OutboxEvent.event_type == "website.page.published",
            )
        )
    assert count == 2
    assert audit_count == 5
    assert published_events == 1


async def test_website_cms_revision_restore_and_authenticated_preview(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    slug = "cms-restore-" + uuid4().hex[:12]
    first = page_document(slug, "Original first version")
    response = await client.post("/api/v1/site-cms/pages", headers=auth_headers, json=first)
    assert response.status_code == 201, response.text
    page_id = response.json()["id"]

    other = page_document(slug, "Second version")
    revised = await client.put("/api/v1/site-cms/pages/" + page_id, headers=auth_headers,
                               json={"expected_version": 1, "document": other})
    assert revised.status_code == 200, revised.text
    assert revised.json()["draftVersion"] == 2

    revisions = await client.get("/api/v1/site-cms/pages/" + page_id + "/revisions", headers=auth_headers)
    assert revisions.status_code == 200, revisions.text
    assert [row["version"] for row in revisions.json()] == [2, 1]

    anonymous_preview = await client.get("/api/v1/site-cms/pages/" + page_id + "/preview")
    assert anonymous_preview.status_code == 401
    preview = await client.get("/api/v1/site-cms/pages/" + page_id + "/preview",
                               headers=auth_headers)
    assert preview.status_code == 200, preview.text
    assert "Second version" in preview.text
    assert "noindex" in preview.headers["x-robots-tag"]
    assert "private, no-store" in preview.headers["cache-control"]

    restored = await client.post(
        "/api/v1/site-cms/pages/" + page_id + "/restore/1",
        headers=auth_headers, json={"expected_version": 2},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["draftVersion"] == 3
    assert restored.json()["document"]["nodes"][0]["children"][0]["text"] == "Original first version"

    history = await client.get("/api/v1/site-cms/pages/" + page_id + "/revisions",
                               headers=auth_headers)
    assert [item["version"] for item in history.json()] == [3, 2, 1]
    stale_restore = await client.post(
        "/api/v1/site-cms/pages/" + page_id + "/restore/1",
        headers=auth_headers, json={"expected_version": 2},
    )
    assert stale_restore.status_code == 409



async def test_duplicate_page_is_independent_private_and_search_safe(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    prefix = uuid4().hex[:12]
    original_slug = "original-" + prefix
    copy_slug = "copied-" + prefix
    original_document = page_document(original_slug, "Original headline")
    original_document["seo"] = {
        "description": "Approved search summary",
        "canonical_url": "https://example.org/" + original_slug,
        "indexable": True,
    }
    created = await client.post(
        "/api/v1/site-cms/pages", headers=auth_headers, json=original_document,
    )
    assert created.status_code == 201, created.text
    source = created.json()
    url = "/api/v1/site-cms/pages/" + source["id"] + "/duplicate"
    payload = {"slug": copy_slug, "title": "Independent copy"}

    no_auth = await client.post(url, json=payload)
    assert no_auth.status_code == 401

    duplicate = await client.post(url, headers=auth_headers, json=payload)
    assert duplicate.status_code == 201, duplicate.text
    copied = duplicate.json()
    assert copied["id"] != source["id"]
    assert copied["status"] == "draft"
    assert copied["draftVersion"] == 1
    assert copied["publishedVersion"] is None
    assert copied["slug"] == copy_slug
    assert copied["title"] == "Independent copy"
    assert copied["document"]["seo"]["indexable"] is False
    assert copied["document"]["seo"]["canonical_url"] is None
    assert copied["document"]["seo"]["description"] == "Approved search summary"
    original_nodes = source["document"]["nodes"]
    cloned_nodes = copied["document"]["nodes"]
    assert original_nodes[0]["id"] != cloned_nodes[0]["id"]
    assert original_nodes[0]["children"][0]["id"] != cloned_nodes[0]["children"][0]["id"]
    assert original_nodes[0]["children"][0]["text"] == cloned_nodes[0]["children"][0]["text"]

    duplicate_again = await client.post(url, headers=auth_headers, json=payload)
    assert duplicate_again.status_code == 409

    invalid = await client.post(url, headers=auth_headers, json={
        "slug": "../unsafe", "title": "Unsafe URL",
    })
    assert invalid.status_code == 422

    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200
    response = await client.get(
        "/api/v1/site-cms/public/" + workspace.json()["id"] + "/" + copy_slug
    )
    assert response.status_code == 404

    async with SessionFactory() as session:
        copied_revisions = await session.scalar(
            select(func.count()).select_from(WebsiteRevision)
            .where(WebsiteRevision.page_id == UUID(copied["id"]))
        )
        audits = await session.scalar(
            select(func.count()).select_from(WebsiteAudit)
            .where(WebsiteAudit.page_id == UUID(copied["id"]))
        )
    assert copied_revisions == 1
    assert audits == 1



async def test_owner_export_import_creates_independent_unpublished_page(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    suffix = uuid4().hex[:12]
    source_slug = "export-source-" + suffix
    destination_slug = "import-destination-" + suffix
    document = page_document(source_slug, "Source content")
    document["seo"] = {
        "indexable": True,
        "canonical_url": "https://example.org/" + source_slug,
        "description": "Approved information",
    }
    created = await client.post(
        "/api/v1/site-cms/pages", headers=auth_headers, json=document,
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    export_path = f"/api/v1/site-cms/pages/{page_id}/export"
    unauth_export = await client.get(export_path)
    assert unauth_export.status_code == 401

    exported = await client.get(export_path, headers=auth_headers)
    assert exported.status_code == 200, exported.text
    assert exported.headers["cache-control"] == "private, no-store"
    manifest = exported.json()
    assert manifest["format"] == "northstar.site-page"
    assert manifest["version"] == 1
    assert manifest["page"]["slug"] == source_slug
    assert manifest["page"]["seo"]["indexable"] is True

    payload = {
        **manifest, "new_slug": destination_slug, "new_title": "Imported private page",
    }
    unauth_import = await client.post("/api/v1/site-cms/pages/import", json=payload)
    assert unauth_import.status_code == 401

    imported = await client.post(
        "/api/v1/site-cms/pages/import", headers=auth_headers, json=payload,
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()
    assert copy["id"] != page_id
    assert copy["slug"] == destination_slug
    assert copy["status"] == "draft"
    assert copy["publishedVersion"] is None
    assert copy["document"]["seo"]["canonical_url"] is None
    assert copy["document"]["seo"]["indexable"] is False
    assert copy["document"]["nodes"][0]["children"][0]["text"] == "Source content"
    assert copy["document"]["nodes"][0]["id"] != manifest["page"]["nodes"][0]["id"]

    repeated = await client.post(
        "/api/v1/site-cms/pages/import", headers=auth_headers, json=payload,
    )
    assert repeated.status_code == 409
    bad_format = await client.post(
        "/api/v1/site-cms/pages/import",
        headers=auth_headers,
        json={**payload, "format": "unknown-format"},
    )
    assert bad_format.status_code == 422
    extra_field = await client.post(
        "/api/v1/site-cms/pages/import",
        headers=auth_headers,
        json={**payload, "untrusted_html": "<script>bad()</script>"},
    )
    assert extra_field.status_code == 422

    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    public = await client.get(
        f"/api/v1/site-cms/public/{workspace.json()['id']}/{destination_slug}"
    )
    assert public.status_code == 404
    unmodified_source = await client.get(export_path, headers=auth_headers)
    assert unmodified_source.json()["page"]["seo"]["indexable"] is True

    async with SessionFactory() as session:
        saved_revisions = await session.scalar(
            select(func.count()).select_from(WebsiteRevision)
            .where(WebsiteRevision.page_id == UUID(copy["id"]))
        )
        events = await session.scalar(
            select(func.count()).select_from(WebsiteAudit)
            .where(WebsiteAudit.page_id == UUID(copy["id"]), WebsiteAudit.action == "import")
        )
    assert saved_revisions == 1
    assert events == 1



async def test_archiving_hides_published_page_without_deleting_revisions(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    prefix = uuid4().hex[:12]
    slug = "archive-cms-" + prefix
    document = page_document(slug, "Preserved published content")
    document["seo"] = {
        "description": "Public page subject to manual archival",
        "canonical_url": "https://example.org/" + slug,
        "indexable": True,
    }
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200
    workspace_id = workspace.json()["id"]
    public_path = f"/api/v1/site-cms/public/{workspace_id}/{slug}"
    sitemap_path = f"/api/v1/site-discovery/sitemap/{workspace_id}.xml"

    created = await client.post("/api/v1/site-cms/pages", headers=auth_headers, json=document)
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    action_path = f"/api/v1/site-cms/pages/{page_id}/"
    for action in ("submit", "approve", "publish"):
        done = await client.post(action_path + action, headers=auth_headers)
        assert done.status_code == 200, done.text

    assert (await client.get(public_path)).status_code == 200
    assert "https://example.org/" + slug in (await client.get(sitemap_path)).text

    archive = await client.post(action_path + "archive", headers=auth_headers)
    assert archive.status_code == 200, archive.text
    assert archive.json()["status"] == "archived"
    assert archive.json()["publishedVersion"] is None
    assert (await client.get(public_path)).status_code == 404
    assert "https://example.org/" + slug not in (await client.get(sitemap_path)).text

    anonymous_restore = await client.post(action_path + "restore_draft")
    assert anonymous_restore.status_code == 401
    restored = await client.post(action_path + "restore_draft", headers=auth_headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "draft"
    assert restored.json()["document"]["nodes"][0]["children"][0]["text"] == "Preserved published content"
    assert (await client.get(public_path)).status_code == 404

    for action, state in (
        ("submit", "in_review"), ("request_changes", "draft"),
        ("submit", "in_review"), ("approve", "approved"), ("publish", "published"),
    ):
        response = await client.post(action_path + action, headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == state
    assert (await client.get(public_path)).status_code == 200

    updated = page_document(slug, "Unpublished new draft")
    saved = await client.put(
        f"/api/v1/site-cms/pages/{page_id}",
        headers=auth_headers,
        json={"expected_version": 1, "document": updated},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "draft"
    assert saved.json()["publishedVersion"] == 1

    old_live = await client.get(public_path)
    assert old_live.status_code == 200, old_live.text
    assert "Preserved published content" in old_live.text
    assert "Unpublished new draft" not in old_live.text

    async with SessionFactory() as session:
        revision_count = await session.scalar(
            select(func.count()).select_from(WebsiteRevision)
            .where(WebsiteRevision.page_id == UUID(page_id))
        )
        unpublished_events = await session.scalar(
            select(func.count()).select_from(OutboxEvent)
            .where(
                OutboxEvent.aggregate_type == "website_page",
                OutboxEvent.aggregate_id == page_id,
                OutboxEvent.event_type == "website.page.unpublished",
            )
        )
    assert revision_count == 2
    assert unpublished_events == 1
