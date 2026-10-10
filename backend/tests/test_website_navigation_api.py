"""Cross-stack CMS navigation: tenant-scoped drafts, publishing and public links."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.models import OutboxEvent
from northstar_api.website_cms_models import WebsiteSiteMenu, WebsiteSiteMenuAudit, WebsiteSiteMenuRevision


def _content(slug: str, heading: str) -> dict:
    return {
        "schema_version": 1, "slug": slug, "title": heading,
        "nodes": [{"id": "section", "kind": "section", "children": [
            {"id": "heading", "kind": "heading", "text": heading},
        ]}],
    }


async def _page(client: AsyncClient, headers: dict[str, str], slug: str, title: str) -> str:
    result = await client.post(
        "/api/v1/site-cms/pages", headers=headers, json=_content(slug, title),
    )
    assert result.status_code == 201, result.text
    return result.json()["id"]


async def _publish_page(client: AsyncClient, headers: dict[str, str], page_id: str) -> None:
    for action in ("submit", "approve", "publish"):
        result = await client.post(
            f"/api/v1/site-cms/pages/{page_id}/{action}", headers=headers,
        )
        assert result.status_code == 200, result.text


async def test_menu_draft_requires_owner_and_published_link_targets(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200
    workspace_id = workspace.json()["id"]
    slug = "nav-page-" + uuid4().hex[:12]
    page_id = await _page(client, auth_headers, slug, "About us")
    menu_path = "/api/v1/site-cms/menu"
    assert (await client.get(menu_path)).status_code == 401
    initial = await client.get(menu_path, headers=auth_headers)
    assert initial.status_code == 200, initial.text
    starting_version = initial.json()["draftVersion"]

    menu = {"items": [{"id": "nav-about", "label": "About & <script>", "slug": slug}]}
    unauth_save = await client.put(menu_path, json={
        "expected_version": starting_version, "document": menu,
    })
    assert unauth_save.status_code == 401
    first = await client.put(menu_path, headers=auth_headers, json={
        "expected_version": starting_version, "document": menu,
    })
    assert first.status_code == 200, first.text
    assert first.json()["draftVersion"] == starting_version + 1
    assert first.json()["publishedVersion"] == initial.json()["publishedVersion"]

    stale = await client.put(menu_path, headers=auth_headers, json={
        "expected_version": starting_version, "document": menu,
    })
    assert stale.status_code == 409

    premature = await client.post(
        menu_path + "/publish", headers=auth_headers, json={"expected_version": starting_version + 1},
    )
    assert premature.status_code == 409
    assert slug in premature.text

    await _publish_page(client, auth_headers, page_id)
    public_url = f"/api/v1/site-cms/public/{workspace_id}/{slug}"
    before = await client.get(public_url)
    assert before.status_code == 200
    assert 'About &amp; &lt;script&gt;' not in before.text

    published = await client.post(
        menu_path + "/publish", headers=auth_headers, json={"expected_version": starting_version + 1},
    )
    assert published.status_code == 200, published.text
    assert published.json()["publishedVersion"] == starting_version + 1

    public = await client.get(public_url)
    assert public.status_code == 200, public.text
    assert 'aria-label="Primary navigation"' in public.text
    assert 'About &amp; &lt;script&gt;' in public.text
    assert '<script>About' not in public.text
    assert f'href="{public_url}"' in public.text

    # Capture post-publication totals: a retry must not duplicate side effects.
    async with SessionFactory() as session:
        saved_menu = await session.scalar(select(WebsiteSiteMenu).where(
            WebsiteSiteMenu.workspace_id == UUID(workspace_id),
        ))
        assert saved_menu is not None
        prior_audits = await session.scalar(select(func.count()).select_from(WebsiteSiteMenuAudit).where(
            WebsiteSiteMenuAudit.menu_id == saved_menu.id,
            WebsiteSiteMenuAudit.action == "publish",
        ))
        prior_events = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_type == "website_menu",
            OutboxEvent.aggregate_id == str(saved_menu.id),
            OutboxEvent.event_type == "website.menu.published",
        ))
    # Repeated publish does not generate a second audit/outbox message.
    repeated = await client.post(
        menu_path + "/publish", headers=auth_headers, json={"expected_version": starting_version + 1},
    )
    assert repeated.status_code == 200

    async with SessionFactory() as session:
        menu_row = await session.scalar(
            select(WebsiteSiteMenu).where(WebsiteSiteMenu.workspace_id == UUID(workspace_id)),
        )
        assert menu_row is not None
        audit_count = await session.scalar(select(func.count()).select_from(WebsiteSiteMenuAudit).where(
            WebsiteSiteMenuAudit.menu_id == menu_row.id,
            WebsiteSiteMenuAudit.action == "publish",
        ))
        event_count = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_type == "website_menu",
            OutboxEvent.aggregate_id == str(menu_row.id),
            OutboxEvent.event_type == "website.menu.published",
        ))
    assert prior_audits is not None and prior_audits >= 1
    assert prior_events is not None and prior_events >= 1
    assert audit_count == prior_audits
    assert event_count == prior_events


async def test_menu_immutable_public_version_restore_and_archival(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    workspace_id = workspace.json()["id"]
    slug_a = "nav-a-" + uuid4().hex[:12]
    slug_b = "nav-b-" + uuid4().hex[:12]
    page_a = await _page(client, auth_headers, slug_a, "First")
    page_b = await _page(client, auth_headers, slug_b, "Second")
    await _publish_page(client, auth_headers, page_a)
    await _publish_page(client, auth_headers, page_b)
    menu_path = "/api/v1/site-cms/menu"
    current_menu = await client.get(menu_path, headers=auth_headers)
    assert current_menu.status_code == 200, current_menu.text
    base_version = current_menu.json()["draftVersion"]
    link_a = {"id": "item-a", "label": "First", "slug": slug_a}
    link_b = {"id": "item-b", "label": "Second", "slug": slug_b}

    saved = await client.put(menu_path, headers=auth_headers, json={
        "expected_version": base_version, "document": {"items": [link_a]},
    })
    assert saved.status_code == 200, saved.text
    assert (await client.post(
        menu_path + "/publish", headers=auth_headers, json={"expected_version": base_version + 1},
    )).status_code == 200

    edited = await client.put(menu_path, headers=auth_headers, json={
        "expected_version": base_version + 1, "document": {"items": [link_b]},
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["draftVersion"] == base_version + 2
    assert edited.json()["publishedVersion"] == base_version + 1

    public_url = f"/api/v1/site-cms/public/{workspace_id}/{slug_a}"
    preview_live = await client.get(public_url)
    assert f">{link_a['label']}</a>" in preview_live.text
    assert f">{link_b['label']}</a>" not in preview_live.text

    promoted = await client.post(
        menu_path + "/publish", headers=auth_headers, json={"expected_version": base_version + 2},
    )
    assert promoted.status_code == 200
    assert f">{link_b['label']}</a>" in (await client.get(public_url)).text
    revisions = await client.get(menu_path + "/revisions", headers=auth_headers)
    assert [entry["version"] for entry in revisions.json()[:2]] == [base_version + 2, base_version + 1]

    restored = await client.post(
        menu_path + "/restore/" + str(base_version + 1), headers=auth_headers, json={"expected_version": base_version + 2},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["draftVersion"] == base_version + 3
    assert restored.json()["publishedVersion"] == base_version + 2
    assert restored.json()["document"]["items"] == [link_a]
    assert f">{link_b['label']}</a>" in (await client.get(public_url)).text

    assert (await client.post(
        menu_path + "/publish", headers=auth_headers, json={"expected_version": base_version + 3},
    )).status_code == 200
    assert f">{link_a['label']}</a>" in (await client.get(public_url)).text

    archived = await client.post(
        f"/api/v1/site-cms/pages/{page_a}/archive", headers=auth_headers,
    )
    assert archived.status_code == 200
    live_other_page = await client.get(f"/api/v1/site-cms/public/{workspace_id}/{slug_b}")
    assert live_other_page.status_code == 200
    assert 'aria-label="Primary navigation"' not in live_other_page.text
    # No automatic deletion of historical menu content after archiving a destination.
    history = await client.get(menu_path, headers=auth_headers)
    assert history.json()["document"]["items"] == [link_a]

    stale_restore = await client.post(
        menu_path + "/restore/" + str(base_version + 1), headers=auth_headers, json={"expected_version": base_version + 2},
    )
    assert stale_restore.status_code == 409


async def test_menu_rejects_unsafe_urls_and_duplicate_or_unbounded_links(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    url = "/api/v1/site-cms/menu"
    unsafe = [
        {"id": "x", "label": "External", "slug": "https://malicious.example"},
        {"id": "x", "label": "", "slug": "hello"},
        {"id": "x", "label": "Unsafe", "slug": "../admin"},
    ]
    for item in unsafe:
        reply = await client.put(url, headers=auth_headers, json={
            "expected_version": 0, "document": {"items": [item]},
        })
        assert reply.status_code == 422, reply.text

    duplicates = await client.put(url, headers=auth_headers, json={
        "expected_version": 0,
        "document": {"items": [
            {"id": "same", "label": "First", "slug": "first"},
            {"id": "same", "label": "Second", "slug": "second"},
        ]},
    })
    assert duplicates.status_code == 422
    overflow = await client.put(url, headers=auth_headers, json={
        "expected_version": 0,
        "document": {"items": [
            {"id": str(i), "label": str(i), "slug": "page-" + str(i)}
            for i in range(21)
        ]},
    })
    assert overflow.status_code == 422


async def test_preflight_flags_navigation_to_archived_pages(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    workspace_id = workspace.json()["id"]
    slug = "preflight-target-" + uuid4().hex[:8]
    page_id = await _page(client, auth_headers, slug, "Preflight target")
    await _publish_page(client, auth_headers, page_id)
    menu_url = "/api/v1/site-cms/menu"
    prior = await client.get(menu_url, headers=auth_headers)
    assert prior.status_code == 200, prior.text
    baseline = prior.json()
    saved = await client.put(menu_url, headers=auth_headers, json={
        "expected_version": baseline["draftVersion"],
        "document": {
            "items": [{"id": "preflight-item", "label": "Old menu link", "slug": slug}],
        },
    })
    assert saved.status_code == 200, saved.text
    new_version = saved.json()["draftVersion"]
    promoted = await client.post(
        menu_url + "/publish", headers=auth_headers,
        json={"expected_version": new_version},
    )
    assert promoted.status_code == 200, promoted.text
    retired = await client.post(
        f"/api/v1/site-cms/pages/{page_id}/archive", headers=auth_headers,
    )
    assert retired.status_code == 200, retired.text
    preflight = await client.get("/api/v1/site-cms/preflight", headers=auth_headers)
    assert preflight.status_code == 200, preflight.text
    report = preflight.json()
    assert report["scope"] == "cms-content-only"
    assert report["contentReady"] is False
    assert any(
        issue["code"] == "BROKEN_MENU_LINK" and issue["slug"] == slug
        and issue["severity"] == "blocker"
        for issue in report["issues"]
    )
    assert report["releaseCertified"] is False
    assert str(workspace_id) not in str(report["issues"])

    # Restore the previously saved menu as a new version so this shared
    # test workspace does not leave a broken public navigation pointer.
    visible = await client.get("/api/v1/site-cms/pages", headers=auth_headers)
    assert visible.status_code == 200
    currently_published = {
        item["slug"] for item in visible.json()
        if item["publishedVersion"] is not None
    }
    restore_doc = {
        "items": [
            item for item in baseline["document"]["items"]
            if item["slug"] in currently_published
        ],
    }
    restored = await client.put(menu_url, headers=auth_headers, json={
        "expected_version": new_version,
        "document": restore_doc,
    })
    assert restored.status_code == 200, restored.text
    restore_published = await client.post(
        menu_url + "/publish", headers=auth_headers,
        json={"expected_version": restored.json()["draftVersion"]},
    )
    assert restore_published.status_code == 200, restore_published.text
