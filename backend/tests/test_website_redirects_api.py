"""Owner-controlled redirects live in the existing CMS, not a parallel router."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.models import OutboxEvent
from northstar_api.website_cms_models import WebsiteRedirect, WebsiteRedirectAudit


def _document(slug: str, title: str) -> dict:
    return {
        "schema_version": 1,
        "slug": slug,
        "title": title,
        "nodes": [{"id": "section", "kind": "section", "children": [
            {"id": "heading", "kind": "heading", "text": title},
        ]}],
    }


async def _create_public(
    client: AsyncClient, headers: dict[str, str], slug: str, title: str,
) -> str:
    created = await client.post(
        "/api/v1/site-cms/pages", headers=headers, json=_document(slug, title),
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    for action in ("submit", "approve", "publish"):
        result = await client.post(
            f"/api/v1/site-cms/pages/{page_id}/{action}", headers=headers,
        )
        assert result.status_code == 200, result.text
    return page_id


async def test_internal_301_equivalent_redirects_are_safe_and_versioned(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    scope = await client.get("/api/v1/workspace", headers=auth_headers)
    workspace_id = scope.json()["id"]
    destination = "new-landing-" + uuid4().hex[:12]
    old_slug = "old-landing-" + uuid4().hex[:12]
    second = "new-other-" + uuid4().hex[:12]
    page_id = await _create_public(client, auth_headers, destination, "New landing")
    await _create_public(client, auth_headers, second, "Second landing")
    base = "/api/v1/site-cms/redirects"

    assert (await client.get(base)).status_code == 401
    payload = {"source_slug": old_slug, "target_slug": destination, "status_code": 308}
    assert (await client.post(base, json=payload)).status_code == 401

    created = await client.post(base, headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["enabled"] is True
    assert row["statusCode"] == 308
    assert row["version"] == 1
    redirect_id = row["id"]
    old_public = f"/api/v1/site-cms/public/{workspace_id}/{old_slug}"
    new_public = f"/api/v1/site-cms/public/{workspace_id}/{destination}"

    public = await client.get(old_public, follow_redirects=False)
    assert public.status_code == 308, public.text
    assert public.headers["location"] == new_public
    assert public.headers["cache-control"] == "no-store"
    assert (await client.get(new_public)).status_code == 200

    duplicate = await client.post(base, headers=auth_headers, json=payload)
    assert duplicate.status_code == 409

    edited = await client.put(
        base + "/" + redirect_id, headers=auth_headers,
        json={"expected_version": 1, "target_slug": second, "status_code": 307, "enabled": True},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2
    assert edited.json()["statusCode"] == 307
    changed_public = await client.get(old_public, follow_redirects=False)
    assert changed_public.status_code == 307
    assert changed_public.headers["location"].endswith("/" + second)

    stale = await client.put(
        base + "/" + redirect_id, headers=auth_headers,
        json={"expected_version": 1, "target_slug": destination, "status_code": 308, "enabled": True},
    )
    assert stale.status_code == 409

    disabled = await client.put(
        base + "/" + redirect_id, headers=auth_headers,
        json={"expected_version": 2, "target_slug": second, "status_code": 307, "enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False
    assert (await client.get(old_public, follow_redirects=False)).status_code == 404

    listed = await client.get(base, headers=auth_headers)
    assert listed.status_code == 200
    assert any(rule["id"] == redirect_id and rule["version"] == 3 for rule in listed.json())

    async with SessionFactory() as session:
        audit_count = await session.scalar(select(func.count()).select_from(WebsiteRedirectAudit).where(
            WebsiteRedirectAudit.redirect_id == UUID(redirect_id),
        ))
        redirect = await session.scalar(select(WebsiteRedirect).where(
            WebsiteRedirect.id == UUID(redirect_id),
        ))
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_type == "website_redirect",
            OutboxEvent.aggregate_id == redirect_id,
        ))
    assert audit_count == 3
    assert outbox_count == 3
    assert redirect is not None and redirect.source_slug == old_slug

    # Do not redirect to a page after its publication was archived.
    page_archived = await client.post(
        f"/api/v1/site-cms/pages/{page_id}/archive", headers=auth_headers,
    )
    assert page_archived.status_code == 200
    unavailable = await client.post(base, headers=auth_headers, json={
        "source_slug": "unknown-after-archive-" + uuid4().hex[:8],
        "target_slug": destination, "status_code": 308,
    })
    assert unavailable.status_code == 409


async def test_redirect_can_preserve_an_archived_url_without_deleting_page_history(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    workspace_id = workspace.json()["id"]
    old_slug = "retired-" + uuid4().hex[:12]
    new_slug = "replacement-" + uuid4().hex[:12]
    old_page = await _create_public(client, auth_headers, old_slug, "Old campaign")
    await _create_public(client, auth_headers, new_slug, "New campaign")
    assert (await client.post(
        f"/api/v1/site-cms/pages/{old_page}/archive", headers=auth_headers,
    )).status_code == 200

    created = await client.post(
        "/api/v1/site-cms/redirects", headers=auth_headers,
        json={"source_slug": old_slug, "target_slug": new_slug, "status_code": 308},
    )
    assert created.status_code == 201, created.text
    moved = await client.get(
        f"/api/v1/site-cms/public/{workspace_id}/{old_slug}", follow_redirects=False,
    )
    assert moved.status_code == 308, moved.text
    assert moved.headers["location"].endswith("/" + new_slug)

    source_again = await client.post(
        "/api/v1/site-cms/pages", headers=auth_headers,
        json=_document(old_slug, "Colliding new page"),
    )
    assert source_again.status_code == 409

    still_stored = await client.get("/api/v1/site-cms/pages", headers=auth_headers)
    assert any(item["id"] == old_page and item["status"] == "archived"
               for item in still_stored.json())


async def test_redirect_rejects_open_redirects_and_active_url_takeover(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    active_slug = "active-page-" + uuid4().hex[:12]
    await _create_public(client, auth_headers, active_slug, "Active page")
    base = "/api/v1/site-cms/redirects"
    test_cases = [
        ({"source_slug": "unsafe", "target_slug": "https://evil.example", "status_code": 308}, 422),
        ({"source_slug": "../private", "target_slug": active_slug, "status_code": 308}, 422),
        ({"source_slug": "self", "target_slug": "self", "status_code": 308}, 422),
        ({"source_slug": "unpublished", "target_slug": "missing", "status_code": 308}, 409),
        ({"source_slug": active_slug, "target_slug": active_slug, "status_code": 308}, 422),
    ]
    for payload, expected in test_cases:
        reply = await client.post(base, headers=auth_headers, json=payload)
        assert reply.status_code == expected, reply.text

    another_slug = "other-page-" + uuid4().hex[:12]
    await _create_public(client, auth_headers, another_slug, "Other page")
    active_takeover = await client.post(base, headers=auth_headers, json={
        "source_slug": active_slug, "target_slug": another_slug, "status_code": 308,
    })
    assert active_takeover.status_code == 409
