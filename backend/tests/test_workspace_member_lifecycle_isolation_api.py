"""Lifecycle mutations and status reads must stay inside the selected workspace."""
from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient


async def test_workspace_member_lifecycle_is_isolated_between_workspaces(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    tokens: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        tokens.append(kwargs["raw_token"])

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        capture_invitation,
    )
    primary = await client.get("/api/v1/workspace", headers=auth_headers)
    assert primary.status_code == 200, primary.text
    primary_id = primary.json()["id"]
    primary_headers = {**auth_headers, "X-Workspace-ID": primary_id}
    other = await client.post(
        "/api/v1/workspaces", headers=primary_headers,
        json={"name": "Member Isolation Secondary", "slug": f"member-isolation-{uuid4().hex[:16]}"},
    )
    assert other.status_code == 201, other.text
    other_headers = {**auth_headers, "X-Workspace-ID": other.json()["id"]}
    invited = await client.post(
        "/api/v1/workspace/invitations", headers=primary_headers,
        json={
            "email": f"member-isolation-{uuid4().hex}@example.com",
            "role": "operator", "allAgentsAccess": True, "agentIds": [],
        },
    )
    assert invited.status_code == 201, invited.text
    assert tokens
    signup = await client.post(
        "/api/v1/workspace-invitations/signup",
        json={
            "token": tokens[-1], "name": "Scoped Lifecycle Fixture",
            "password": "Scoped-Lifecycle-Password-42!",
            "termsAccepted": True, "privacyAccepted": True,
        },
    )
    assert signup.status_code == 201, signup.text
    user_id = signup.json()["user"]["id"]
    member_headers = {
        "Authorization": f"Bearer {signup.json()['accessToken']}",
        "X-Workspace-ID": primary_id,
    }
    suspended = await client.post(
        f"/api/v1/workspace/members/{user_id}/suspend",
        headers=primary_headers,
        json={"reason": "Verify per-workspace access", "confirmation": "SUSPEND"},
    )
    assert suspended.status_code == 200, suspended.text
    other_statuses = await client.get(
        "/api/v1/workspace/members/lifecycle", headers=other_headers,
    )
    assert other_statuses.status_code == 200, other_statuses.text
    assert user_id not in {entry["userId"] for entry in other_statuses.json()}
    wrong_reactivation = await client.post(
        f"/api/v1/workspace/members/{user_id}/reactivate", headers=other_headers,
        json={"reason": "Wrong workspace cannot change member", "confirmation": "REACTIVATE"},
    )
    assert wrong_reactivation.status_code == 404, wrong_reactivation.text
    wrong_suspension = await client.post(
        f"/api/v1/workspace/members/{user_id}/suspend", headers=other_headers,
        json={"reason": "Wrong workspace cannot change member", "confirmation": "SUSPEND"},
    )
    assert wrong_suspension.status_code == 404, wrong_suspension.text
    primary_statuses = await client.get(
        "/api/v1/workspace/members/lifecycle", headers=primary_headers,
    )
    assert primary_statuses.status_code == 200, primary_statuses.text
    assert next(entry for entry in primary_statuses.json() if entry["userId"] == user_id)["status"] == "suspended"
    assert (await client.get("/api/v1/workspace", headers=member_headers)).status_code == 403
    restored = await client.post(
        f"/api/v1/workspace/members/{user_id}/reactivate", headers=primary_headers,
        json={"reason": "Isolation review completed", "confirmation": "REACTIVATE"},
    )
    assert restored.status_code == 200, restored.text
    assert (await client.get("/api/v1/workspace", headers=member_headers)).status_code == 200
    removed = await client.delete(
        f"/api/v1/workspace/members/{user_id}", headers=primary_headers,
    )
    assert removed.status_code == 204, removed.text
