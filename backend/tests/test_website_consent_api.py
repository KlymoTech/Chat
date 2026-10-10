"""End-to-end API boundary tests for first-party website consent choices."""
from __future__ import annotations

from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.main import app
from northstar_api.website_consent_models import WebsiteConsentReceipt


async def _workspace_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    result = await client.get("/api/v1/workspace", headers=auth_headers)
    assert result.status_code == 200, result.text
    return result.json()["id"]


async def test_anonymous_visitor_defaults_to_rejected_and_can_withdraw(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace_id = await _workspace_id(client, auth_headers)
    url = "/api/v1/site-consent/" + workspace_id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as visitor:
        unknown = await visitor.get(url)
        assert unknown.status_code == 200, unknown.text
        assert unknown.json()["necessary"] is True
        assert unknown.json()["analytics"] is False
        assert unknown.json()["marketing"] is False
        assert unknown.json()["personalization"] is False
        assert unknown.json()["decisions"]["analytics"]["reason"] == "missing_receipt"
        assert unknown.headers["cache-control"] == "private, no-store"

        allowed = await visitor.post(url, json={
            "analytics": True, "marketing": True, "personalization": False,
        })
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["analytics"] is True
        assert allowed.json()["marketing"] is True
        assert allowed.json()["personalization"] is False
        assert "wsc_" in allowed.headers["set-cookie"]
        assert "httponly" in allowed.headers["set-cookie"].lower()

        retained = await visitor.get(url)
        assert retained.status_code == 200
        assert retained.json()["analytics"] is True
        assert retained.json()["marketing"] is True

        refused = await visitor.post(url, json={
            "analytics": False, "marketing": False, "personalization": False,
        })
        assert refused.status_code == 200, refused.text
        assert refused.json()["analytics"] is False
        assert refused.json()["marketing"] is False

        current = await visitor.get(url)
        assert current.json()["analytics"] is False
        assert current.json()["marketing"] is False


async def test_browser_opt_out_prevents_marketing_and_personalization(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace_id = await _workspace_id(client, auth_headers)
    url = "/api/v1/site-consent/" + workspace_id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as visitor:
        gpc = await visitor.post(
            url,
            headers={"Sec-GPC": "1"},
            json={"analytics": True, "marketing": True, "personalization": True},
        )
        assert gpc.status_code == 200, gpc.text
        assert gpc.json()["analytics"] is True
        assert gpc.json()["marketing"] is False
        assert gpc.json()["personalization"] is False
        assert gpc.json()["globalPrivacyControl"] is True
        assert gpc.json()["decisions"]["marketing"]["reason"] == "browser_opt_out"

        # The restrictive consent record persists even when a later read omits the browser signal.
        later = await visitor.get(url)
        assert later.json()["marketing"] is False
        assert later.json()["personalization"] is False


async def test_consent_validation_and_cross_site_updates(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace_id = await _workspace_id(client, auth_headers)
    url = "/api/v1/site-consent/" + workspace_id
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as visitor:
        cross_site = await visitor.post(
            url, headers={"Origin": "https://other.example"},
            json={"analytics": True},
        )
        assert cross_site.status_code == 403
        malformed = await visitor.post(url, json={"analytics": True, "secret": "unexpected"})
        assert malformed.status_code == 422
        invalid_workspace = await visitor.get(
            "/api/v1/site-consent/00000000-0000-0000-0000-000000000000"
        )
        assert invalid_workspace.status_code == 404


async def test_consent_is_append_only_not_overwritten(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    workspace_id = await _workspace_id(client, auth_headers)
    async with SessionFactory() as session:
        before = await session.scalar(
            select(func.count()).select_from(WebsiteConsentReceipt)
            .where(WebsiteConsentReceipt.workspace_id == UUID(workspace_id))
        )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as visitor:
        first = await visitor.post("/api/v1/site-consent/" + workspace_id, json={"analytics": True})
        second = await visitor.post("/api/v1/site-consent/" + workspace_id, json={"analytics": False})
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
    async with SessionFactory() as session:
        after = await session.scalar(
            select(func.count()).select_from(WebsiteConsentReceipt)
            .where(WebsiteConsentReceipt.workspace_id == UUID(workspace_id))
        )
    assert after == (before or 0) + 2
