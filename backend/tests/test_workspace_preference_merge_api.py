"""An older client must not erase new Workspace preferences on PATCH."""
from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient


async def test_legacy_and_nested_partial_patches_preserve_existing_workspace_profile(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert response.status_code == 200, response.text
    original = response.json()["preferences"]
    profile = dict(original)
    profile["industry"] = f"Education-{uuid4().hex[:12]}"
    profile["currency"] = "INR"
    profile["businessHours"] = {
        **original["businessHours"],
        "monday": {"enabled": True, "opens": "08:00", "closes": "18:00"},
    }
    alternate_timezone = "UTC" if original["timezone"] != "UTC" else "Europe/London"
    try:
        expanded = await client.patch("/api/v1/workspace", headers=auth_headers, json={"preferences": profile})
        assert expanded.status_code == 200, expanded.text

        legacy = await client.patch(
            "/api/v1/workspace", headers=auth_headers,
            json={"preferences": {"timezone": alternate_timezone}},
        )
        assert legacy.status_code == 200, legacy.text
        saved = legacy.json()["preferences"]
        assert saved["timezone"] == alternate_timezone
        assert saved["defaultLanguage"] == original["defaultLanguage"]
        assert saved["dateFormat"] == original["dateFormat"]
        assert saved["industry"] == profile["industry"]
        assert saved["currency"] == "INR"
        assert saved["businessHours"]["monday"] == profile["businessHours"]["monday"]

        nested = await client.patch(
            "/api/v1/workspace", headers=auth_headers,
            json={"preferences": {"businessHours": {"monday": {"opens": "07:00"}}}},
        )
        assert nested.status_code == 200, nested.text
        saved = nested.json()["preferences"]
        assert saved["industry"] == profile["industry"]
        assert saved["timezone"] == alternate_timezone
        assert saved["businessHours"]["monday"] == {
            "enabled": True, "opens": "07:00", "closes": "18:00",
        }
        assert saved["businessHours"]["tuesday"] == original["businessHours"]["tuesday"]
        persisted = await client.get("/api/v1/workspace", headers=auth_headers)
        assert persisted.status_code == 200, persisted.text
        assert persisted.json()["preferences"] == saved
    finally:
        restored = await client.patch(
            "/api/v1/workspace", headers=auth_headers,
            json={"preferences": original},
        )
        assert restored.status_code == 200, restored.text
