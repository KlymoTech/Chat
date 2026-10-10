"""Consent-enforced first-party browser event collection, deduplication and reporting."""
from __future__ import annotations

from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from northstar_api.main import app


async def _published_site(client: AsyncClient, auth_headers: dict[str, str]) -> tuple[str, str]:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    slug = "consent-analytics-" + uuid4().hex[:12]
    payload = {
        "schema_version": 1, "slug": slug, "title": "Analytics test",
        "nodes": [{"id": "hero", "kind": "section", "children": [
            {"id": "heading", "kind": "heading", "text": "Welcome"},
            {"id": "call-to-action", "kind": "button", "text": "Continue", "url": "/contact"},
        ]}],
    }
    created = await client.post("/api/v1/site-cms/pages", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    for step in ("submit", "approve", "publish"):
        result = await client.post(
            f"/api/v1/site-cms/pages/{page_id}/{step}", headers=auth_headers,
        )
        assert result.status_code == 200, result.text
    return workspace_id, slug


async def test_events_are_blocked_until_analytics_consent_and_after_withdrawal(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace_id, slug = await _published_site(client, auth_headers)
    endpoint = f"/api/v1/site-analytics/{workspace_id}/events"
    consent = f"/api/v1/site-consent/{workspace_id}"
    event_id = str(uuid4())
    view = {"eventId": event_id, "eventType": "page_view", "slug": slug}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as visitor:
        before = await visitor.post(endpoint, json=view)
        assert before.status_code == 204, before.text

        accepted = await visitor.post(consent, json={"analytics": True})
        assert accepted.status_code == 200, accepted.text

        collected = await visitor.post(endpoint, json=view)
        assert collected.status_code == 200, collected.text
        assert collected.json() == {"status": "accepted"}

        duplicated = await visitor.post(endpoint, json=view)
        assert duplicated.status_code == 200, duplicated.text
        assert duplicated.json() == {"status": "duplicate"}

        conflicting = await visitor.post(endpoint, json={
            "eventId": event_id, "eventType": "cta_click",
            "slug": slug, "blockId": "call-to-action",
        })
        assert conflicting.status_code == 409

        missing_block = await visitor.post(endpoint, json={
            "eventId": str(uuid4()), "eventType": "cta_click", "slug": slug,
        })
        assert missing_block.status_code == 422

        clicked = await visitor.post(endpoint, json={
            "eventId": str(uuid4()), "eventType": "cta_click",
            "slug": slug, "blockId": "call-to-action",
        })
        assert clicked.status_code == 200, clicked.text

        bad_properties = await visitor.post(endpoint, json={
            "eventId": str(uuid4()), "eventType": "page_view",
            "slug": slug, "email": "do-not-store@example.com",
        })
        assert bad_properties.status_code == 422

        withdrawn = await visitor.post(consent, json={"analytics": False})
        assert withdrawn.status_code == 200
        after = await visitor.post(endpoint, json={
            "eventId": str(uuid4()), "eventType": "page_view", "slug": slug,
        })
        assert after.status_code == 204

        other_origin = await visitor.post(endpoint, headers={"Origin": "https://other.example"},
                                          json={"eventId": str(uuid4()), "eventType": "page_view", "slug": slug})
        assert other_origin.status_code == 403

    summary = await client.get("/api/v1/site-analytics/summary", headers=auth_headers)
    assert summary.status_code == 200, summary.text
    matching = [row for row in summary.json()["pages"] if row["slug"] == slug]
    assert matching == [{"slug": slug, "pageViews": 1}]
    assert summary.json()["ctaClicks"] >= 1


async def test_published_pages_load_only_the_server_owned_consent_first_collector(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace_id, slug = await _published_site(client, auth_headers)
    public = await client.get(f"/api/v1/site-cms/public/{workspace_id}/{slug}")
    assert public.status_code == 200, public.text
    assert "/site-analytics/client.js" in public.text
    assert 'data-site-slug="' + slug + '"' in public.text
    assert "script-src 'nonce-" in public.headers["content-security-policy"]
    assert "connect-src 'self'" in public.headers["content-security-policy"]

    sdk = await client.get("/api/v1/site-analytics/client.js")
    assert sdk.status_code == 200, sdk.text
    assert sdk.headers["content-type"].startswith("application/javascript")
    assert "preferences.analytics === true" in sdk.text
    assert "formData" not in sdk.text

    unknown = await client.get("/api/v1/site-analytics/summary")
    assert unknown.status_code == 401


async def test_daily_aggregate_reporting_enforces_authorization_and_date_bounds(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    url = "/api/v1/site-analytics/report"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=auth_headers, params={"days": 0})).status_code == 422
    assert (await client.get(url, headers=auth_headers, params={"days": 91})).status_code == 422
    report = await client.get(url, headers=auth_headers, params={"days": 7})
    assert report.status_code == 200, report.text
    assert report.headers["cache-control"] == "private, no-store"
    assert report.headers["x-content-type-options"] == "nosniff"
    data = report.json()
    assert data["days"] == 7
    assert data["timezone"] == "UTC"
    assert data["deliveryConfirmed"] is False
    assert len(data["daily"]) == 7
    assert data["daily"] == sorted(data["daily"], key=lambda row: row["date"])
    fields = (
        "pageViews", "ctaClicks", "acceptedForms",
        "eventsPublishedToBroker", "eventsQueued", "eventsRetrying",
        "missingOutboxEvents",
    )
    for field in fields:
        assert data["totals"][field] == sum(row[field] for row in data["daily"])
    for row in data["daily"]:
        assert row["missingOutboxEvents"] == max(
            0, row["acceptedForms"] - row["eventsPublishedToBroker"]
            - row["eventsQueued"] - row["eventsRetrying"],
        )
    assert all(
        key not in row for row in data["daily"] for key in
        ("leadId", "emailAddress", "visitorHash", "eventId", "ip")
    )


async def test_daily_reporting_counts_consent_eligible_events_without_contact_data(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace_id, slug = await _published_site(client, auth_headers)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as visitor:
        consent = await visitor.post(
            f"/api/v1/site-consent/{workspace_id}", json={"analytics": True},
        )
        assert consent.status_code == 200, consent.text
        accepted = await visitor.post(
            f"/api/v1/site-analytics/{workspace_id}/events",
            json={"eventId": str(uuid4()), "eventType": "page_view", "slug": slug},
        )
        assert accepted.status_code == 200, accepted.text

    report = await client.get(
        "/api/v1/site-analytics/report", params={"days": 7},
        headers=auth_headers,
    )
    assert report.status_code == 200, report.text
    assert report.json()["totals"]["pageViews"] >= 1
    assert report.json()["totals"]["acceptedForms"] >= 0
    assert report.json()["deliveryConfirmed"] is False
    assert "visitorHash" not in report.text
    assert slug not in report.text  # daily aggregate omits per-page drilldown identifiers
