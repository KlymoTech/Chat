"""Workspace member lifecycle must revoke only Workspace access and be reversible."""
from __future__ import annotations

from httpx import AsyncClient


async def test_suspend_blocks_workspace_principal_and_reactivate_restores_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    delivered_tokens: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        delivered_tokens.append(kwargs["raw_token"])

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        capture_invitation,
    )
    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    workspace_id = current.json()["id"]
    scoped_headers = {**auth_headers, "X-Workspace-ID": workspace_id}

    invited_email = "workspace-lifecycle@example.com"
    invitation = await client.post(
        "/api/v1/workspace/invitations",
        headers=scoped_headers,
        json={
            "email": invited_email,
            "role": "operator",
            "allAgentsAccess": True,
            "agentIds": [],
        },
    )
    assert invitation.status_code == 201, invitation.text
    assert delivered_tokens
    signup = await client.post(
        "/api/v1/workspace-invitations/signup",
        json={
            "token": delivered_tokens[-1],
            "name": "Lifecycle Member",
            "password": "Lifecycle-Member-Password-42!",
            "termsAccepted": True,
            "privacyAccepted": True,
        },
    )
    assert signup.status_code == 201, signup.text
    member_headers = {
        "Authorization": f"Bearer {signup.json()['accessToken']}",
        "X-Workspace-ID": workspace_id,
    }
    assert (await client.get("/api/v1/workspace", headers=member_headers)).status_code == 200

    members = await client.get("/api/v1/workspace/members", headers=scoped_headers)
    assert members.status_code == 200, members.text
    member = next(item for item in members.json() if item["email"] == invited_email)
    user_id = member["userId"]

    invalid = await client.post(
        f"/api/v1/workspace/members/{user_id}/suspend",
        headers=scoped_headers,
        json={"reason": "Temporary access review", "confirmation": "NO"},
    )
    assert invalid.status_code == 422, invalid.text
    assert (await client.get("/api/v1/workspace", headers=member_headers)).status_code == 200

    suspended = await client.post(
        f"/api/v1/workspace/members/{user_id}/suspend",
        headers=scoped_headers,
        json={"reason": "Temporary access review", "confirmation": "SUSPEND"},
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json() == {"userId": user_id, "status": "suspended"}
    lifecycle = await client.get("/api/v1/workspace/members/lifecycle", headers=scoped_headers)
    assert lifecycle.status_code == 200, lifecycle.text
    assert next(item for item in lifecycle.json() if item["userId"] == user_id)["status"] == "suspended"
    blocked = await client.get("/api/v1/workspace", headers=member_headers)
    assert blocked.status_code == 403, blocked.text
    assert "suspended" in blocked.text.lower()

    repeated = await client.post(
        f"/api/v1/workspace/members/{user_id}/suspend",
        headers=scoped_headers,
        json={"reason": "Still under review", "confirmation": "SUSPEND"},
    )
    assert repeated.status_code == 200, repeated.text

    reactivated = await client.post(
        f"/api/v1/workspace/members/{user_id}/reactivate",
        headers=scoped_headers,
        json={"reason": "Access review completed", "confirmation": "REACTIVATE"},
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json() == {"userId": user_id, "status": "active"}
    restored = await client.get("/api/v1/workspace", headers=member_headers)
    assert restored.status_code == 200, restored.text

    removed = await client.delete(
        f"/api/v1/workspace/members/{user_id}", headers=scoped_headers,
    )
    assert removed.status_code == 204, removed.text


async def test_member_cannot_suspend_self(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    scoped_headers = {**auth_headers, "X-Workspace-ID": current.json()["id"]}
    members = await client.get("/api/v1/workspace/members", headers=scoped_headers)
    assert members.status_code == 200, members.text
    self_member = next(item for item in members.json() if item["isSelf"])
    rejected = await client.post(
        f"/api/v1/workspace/members/{self_member['userId']}/suspend",
        headers=scoped_headers,
        json={"reason": "Self suspension should not be allowed", "confirmation": "SUSPEND"},
    )
    assert rejected.status_code == 409, rejected.text
