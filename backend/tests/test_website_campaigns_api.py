"""Owner campaign URL integration tests: workspace RBAC, validation and UTM encoding."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from urllib.parse import parse_qs, urlsplit


async def test_campaign_link_is_authenticated_and_preserves_normal_parameters(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    payload = {
        "destination": "https://example.org/pricing?ref=partner&utm_source=old",
        "source": "newsletter", "medium": "email", "campaign": "october launch",
        "content": "top_cta",
    }
    unauthenticated = await client.post("/api/v1/site-campaigns/url", json=payload)
    assert unauthenticated.status_code == 401

    result = await client.post("/api/v1/site-campaigns/url", headers=auth_headers, json=payload)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "private, no-store"
    data = result.json()
    assert data["source"] == "newsletter"
    assert data["medium"] == "email"
    assert data["campaign"] == "october launch"

    url = urlsplit(data["url"])
    params = parse_qs(url.query)
    assert url.scheme == "https"
    assert params["ref"] == ["partner"]
    assert params["utm_source"] == ["newsletter"]
    assert params["utm_medium"] == ["email"]
    assert params["utm_campaign"] == ["october launch"]
    assert params["utm_content"] == ["top_cta"]
    assert len(params["utm_source"]) == 1


@pytest.mark.parametrize("destination", [
    "javascript:alert(1)", "/relative", "http://example.org",
    "//example.org", "https://admin:password@example.org",
])
async def test_campaign_link_rejects_unsafe_destinations(
    client: AsyncClient, auth_headers: dict[str, str], destination: str,
) -> None:
    request = {
        "destination": destination, "source": "email", "medium": "email", "campaign": "launch",
    }
    response = await client.post("/api/v1/site-campaigns/url", json=request, headers=auth_headers)
    assert response.status_code == 422, response.text


async def test_campaign_link_rejects_unknown_fields(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    result = await client.post(
        "/api/v1/site-campaigns/url",
        headers=auth_headers,
        json={
            "destination": "https://example.org",
            "source": "newsletter",
            "medium": "email",
            "campaign": "launch",
            "email_address": "forbidden@example.org",
        },
    )
    assert result.status_code == 422, result.text
