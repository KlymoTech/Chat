"""Disabled users remain visible in Workspace member details, not authorized."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient


async def test_disabled_account_remains_visible_only_in_its_workspace(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    from northstar_api.database import SessionFactory
    from northstar_api.models import User

    delivered: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        delivered.append(kwargs["raw_token"])

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        capture_invitation,
    )
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    workspace_id = workspace_response.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    invited_email = f"disabled-details-{uuid4().hex}@example.com"
    issued = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": invited_email, "role": "viewer", "allAgentsAccess": True, "agentIds": [],
    })
    assert issued.status_code == 201, issued.text
    assert delivered
    signup = await client.post("/api/v1/workspace-invitations/signup", json={
        "token": delivered.pop(), "name": "Disabled member details",
        "password": "Disabled-Member-Password-42!", "termsAccepted": True,
        "privacyAccepted": True,
    })
    assert signup.status_code == 201, signup.text
    member_id = UUID(signup.json()["user"]["id"])
    member_headers = {
        "Authorization": f"Bearer {signup.json()['accessToken']}",
        "X-Workspace-ID": workspace_id,
    }
    try:
        async with SessionFactory() as session:
            user = await session.get(User, member_id)
            assert user is not None
            user.is_active = False
            await session.commit()

        details = await client.get("/api/v1/workspace/members/details", headers=headers)
        assert details.status_code == 200, details.text
        disabled = next(item for item in details.json() if item["userId"] == str(member_id))
        assert disabled["status"] == "disabled"
        assert disabled["email"] == invited_email
        assert "token" not in str(disabled).lower()
        assert (await client.get("/api/v1/workspace", headers=member_headers)).status_code == 401

        other = await client.post("/api/v1/workspaces", headers=auth_headers, json={
            "name": "Disabled details isolation", "slug": f"disabled-details-{uuid4().hex[:12]}",
        })
        assert other.status_code == 201, other.text
        other_details = await client.get("/api/v1/workspace/members/details", headers={
            **auth_headers, "X-Workspace-ID": other.json()["id"],
        })
        assert other_details.status_code == 200, other_details.text
        assert str(member_id) not in {item["userId"] for item in other_details.json()}
    finally:
        async with SessionFactory() as session:
            user = await session.get(User, member_id)
            if user is not None:
                user.is_active = True
                await session.commit()
        removed = await client.delete(f"/api/v1/workspace/members/{member_id}", headers=headers)
        assert removed.status_code == 204, removed.text
