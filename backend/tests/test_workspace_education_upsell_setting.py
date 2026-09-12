from httpx import AsyncClient


async def test_workspace_education_upsell_setting_defaults_off_and_persists(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    before = current.json()
    assert before["educationCreateUpsellLeads"] is False

    enabled = await client.patch(
        "/api/v1/workspace",
        headers=auth_headers,
        json={"educationCreateUpsellLeads": True},
    )
    assert enabled.status_code == 200, enabled.text
    enabled_payload = enabled.json()
    assert enabled_payload["educationCreateUpsellLeads"] is True
    assert enabled_payload["name"] == before["name"]
    assert enabled_payload["slug"] == before["slug"]
    assert enabled_payload["preferences"] == before["preferences"]
    assert enabled_payload["whiteLabel"] == before["whiteLabel"]

    reloaded = await client.get("/api/v1/workspace", headers=auth_headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["educationCreateUpsellLeads"] is True

    disabled = await client.patch(
        "/api/v1/workspace",
        headers=auth_headers,
        json={"educationCreateUpsellLeads": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["educationCreateUpsellLeads"] is False
