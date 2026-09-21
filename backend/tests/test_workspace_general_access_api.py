"""Integration checks for General Settings access and workspace selection.

These use existing authentication, API-key and workspace creation pipelines.
The tests never delete user data or alter existing roles.
"""
from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient


async def test_api_key_can_read_workspace_but_cannot_patch_general_settings(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    issued = await client.post(
        "/api/v1/workspace/api-keys", headers=auth_headers,
        json={"name": f"General access regression {uuid4().hex[:8]}"},
    )
    assert issued.status_code == 201, issued.text
    key = issued.json()
    key_headers = {"Authorization": f"Bearer {key['secret']}"}
    try:
        before = await client.get("/api/v1/workspace", headers=key_headers)
        assert before.status_code == 200, before.text
        denied = await client.patch(
            "/api/v1/workspace", headers=key_headers,
            json={"preferences": {"industry": "Unauthorized change"}},
        )
        assert denied.status_code == 403, denied.text
        unchanged = await client.get("/api/v1/workspace", headers=key_headers)
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["preferences"] == before.json()["preferences"]
    finally:
        revoked = await client.delete(
            f"/api/v1/workspace/api-keys/{key['id']}", headers=auth_headers,
        )
        assert revoked.status_code == 204, revoked.text


async def test_nonmember_workspace_selection_denies_general_settings_write(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    original = await client.get("/api/v1/workspace", headers=auth_headers)
    assert original.status_code == 200, original.text
    headers = {**auth_headers, "X-Workspace-ID": str(uuid4())}
    denied = await client.patch(
        "/api/v1/workspace", headers=headers,
        json={"preferences": {"industry": "Wrong workspace"}},
    )
    assert denied.status_code == 403, denied.text
    unchanged = await client.get("/api/v1/workspace", headers=auth_headers)
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["preferences"] == original.json()["preferences"]


async def test_general_preferences_are_isolated_between_selected_workspaces(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    original = await client.get("/api/v1/workspace", headers=auth_headers)
    assert original.status_code == 200, original.text
    slug = f"general-isolation-{uuid4().hex[:16]}"
    secondary = await client.post(
        "/api/v1/workspaces", headers=auth_headers,
        json={"name": "General Isolation Regression", "slug": slug},
    )
    assert secondary.status_code == 201, secondary.text
    secondary_headers = {**auth_headers, "X-Workspace-ID": secondary.json()["id"]}
    new_industry = f"Scoped-{uuid4().hex[:12]}"
    updated = await client.patch(
        "/api/v1/workspace", headers=secondary_headers,
        json={"preferences": {"industry": new_industry}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["preferences"]["industry"] == new_industry
    reread_secondary = await client.get("/api/v1/workspace", headers=secondary_headers)
    assert reread_secondary.status_code == 200, reread_secondary.text
    assert reread_secondary.json()["preferences"]["industry"] == new_industry
    reread_original = await client.get(
        "/api/v1/workspace", headers={**auth_headers, "X-Workspace-ID": original.json()["id"]},
    )
    assert reread_original.status_code == 200, reread_original.text
    assert reread_original.json()["preferences"] == original.json()["preferences"]
