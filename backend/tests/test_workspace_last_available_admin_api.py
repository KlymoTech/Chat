"""HTTP regression: last usable administrator must remain active after a suspend attempt."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient


async def test_suspending_last_available_admin_returns_conflict_without_mutation(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    tokens: list[str] = []

    async def capture_email(**kwargs) -> None:
        tokens.append(kwargs["raw_token"])

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        capture_email,
    )
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}
    email = f"last-available-admin-{uuid4().hex}@example.com"
    issued = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": email, "role": "workspace_admin",
        "allAgentsAccess": True, "agentIds": [],
    })
    assert issued.status_code == 201, issued.text
    assert tokens
    accepted = await client.post("/api/v1/workspace-invitations/signup", json={
        "token": tokens[-1], "name": "Admin guard target",
        "password": "Admin-Guard-Password-42!",
        "termsAccepted": True, "privacyAccepted": True,
    })
    assert accepted.status_code == 201, accepted.text

    members = await client.get("/api/v1/workspace/members", headers=headers)
    assert members.status_code == 200, members.text
    target = next(member for member in members.json() if member["email"] == email)
    assert target["role"] == "workspace_admin"
    target_id = target["userId"]

    # Simulate a concurrent state in which all other admins are unavailable.
    # The owner protection is a separate guard; this checks the new count guard.
    count = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "northstar_api.modules.workspace.services.member_lifecycle.available_workspace_admin_count",
        count,
    )
    denied = await client.post(
        f"/api/v1/workspace/members/{target_id}/suspend",
        headers=headers,
        json={"reason": "Last available admin regression", "confirmation": "SUSPEND"},
    )
    assert denied.status_code == 409, denied.text
    assert "active administrator" in denied.text.lower()
    count.assert_awaited_once()
    lifecycle = await client.get("/api/v1/workspace/members/lifecycle", headers=headers)
    assert lifecycle.status_code == 200, lifecycle.text
    assert next(row for row in lifecycle.json() if row["userId"] == target_id)["status"] == "active"
