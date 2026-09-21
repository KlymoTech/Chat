"""Regression: role edits and removal must preserve another usable administrator."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient


async def test_last_available_admin_cannot_be_demoted_or_removed(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    tokens: list[str] = []

    async def capture_email(**kwargs) -> None:
        tokens.append(kwargs["raw_token"])

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        capture_email,
    )
    selected = await client.get("/api/v1/workspace", headers=auth_headers)
    assert selected.status_code == 200, selected.text
    headers = {**auth_headers, "X-Workspace-ID": selected.json()["id"]}
    email = f"member-admin-guard-{uuid4().hex}@example.com"
    invitation = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": email, "role": "workspace_admin",
        "allAgentsAccess": True, "agentIds": [],
    })
    assert invitation.status_code == 201, invitation.text
    assert tokens
    accepted = await client.post("/api/v1/workspace-invitations/signup", json={
        "token": tokens[-1], "name": "Member admin guard target",
        "password": "Member-Admin-Guard-Password-42!",
        "termsAccepted": True, "privacyAccepted": True,
    })
    assert accepted.status_code == 201, accepted.text
    members = await client.get("/api/v1/workspace/members", headers=headers)
    assert members.status_code == 200, members.text
    member = next(row for row in members.json() if row["email"] == email)
    target_id = member["userId"]

    # No *other usable* administrator: simulate other rows suspended/disabled.
    # Ownership checks remain real; the new count alone is replaced.
    count = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "northstar_api.services.workspace_members.available_workspace_admin_count",
        count,
    )
    changed = await client.patch(
        f"/api/v1/workspace/members/{target_id}", headers=headers,
        json={"role": "viewer", "allAgentsAccess": True, "agentIds": []},
    )
    assert changed.status_code == 409, changed.text
    assert "active administrator" in changed.text.lower()
    removed = await client.delete(f"/api/v1/workspace/members/{target_id}", headers=headers)
    assert removed.status_code == 409, removed.text
    assert count.await_count == 2
    assert all(call.kwargs["exclude_user_id"] == member["userId"] for call in count.await_args_list)

    after = await client.get("/api/v1/workspace/members", headers=headers)
    assert after.status_code == 200, after.text
    remaining = next(row for row in after.json() if row["userId"] == target_id)
    assert remaining["role"] == "workspace_admin"
