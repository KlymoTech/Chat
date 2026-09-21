"""Accepted invitations create exact current-membership provenance, never guesses."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select


async def test_invitation_origin_is_exact_and_disappears_after_member_removal(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    from northstar_api.database import SessionFactory
    from northstar_api.modules.workspace.models.member_invitation_origin import WorkspaceMemberInvitationOrigin

    delivered: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        delivered.append(kwargs["raw_token"])

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        capture_invitation,
    )
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    members = await client.get("/api/v1/workspace/members", headers=headers)
    assert members.status_code == 200, members.text
    inviter_id = next(item["userId"] for item in members.json() if item["isSelf"])

    email = f"origin-{uuid4().hex}@example.com"
    invitation = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": email, "role": "viewer", "allAgentsAccess": True, "agentIds": [],
    })
    assert invitation.status_code == 201, invitation.text
    assert delivered
    invitation_id = UUID(invitation.json()["id"])
    signup = await client.post("/api/v1/workspace-invitations/signup", json={
        "token": delivered.pop(), "name": "Provenance member",
        "password": "Provenance-Member-Password-42!", "termsAccepted": True,
        "privacyAccepted": True,
    })
    assert signup.status_code == 201, signup.text
    member_id = UUID(signup.json()["user"]["id"])
    try:
        async with SessionFactory() as session:
            origin = await session.get(WorkspaceMemberInvitationOrigin, (UUID(workspace_id), member_id))
            assert origin is not None
            assert origin.invitation_id == invitation_id
            assert origin.tenant_id == UUID(signup.json()["tenantId"])

        details = await client.get("/api/v1/workspace/members/details", headers=headers)
        assert details.status_code == 200, details.text
        member = next(item for item in details.json() if item["userId"] == str(member_id))
        assert member["invitedByUserId"] == inviter_id
        assert "token" not in str(member).lower()

        other = await client.post("/api/v1/workspaces", headers=auth_headers, json={
            "name": "Origin isolation", "slug": f"origin-isolation-{uuid4().hex[:12]}",
        })
        assert other.status_code == 201, other.text
        other_details = await client.get("/api/v1/workspace/members/details", headers={
            **auth_headers, "X-Workspace-ID": other.json()["id"],
        })
        assert other_details.status_code == 200, other_details.text
        assert str(member_id) not in {item["userId"] for item in other_details.json()}
    finally:
        removed = await client.delete(f"/api/v1/workspace/members/{member_id}", headers=headers)
        assert removed.status_code == 204, removed.text
        async with SessionFactory() as session:
            assert await session.scalar(select(WorkspaceMemberInvitationOrigin.invitation_id).where(
                WorkspaceMemberInvitationOrigin.workspace_id == UUID(workspace_id),
                WorkspaceMemberInvitationOrigin.user_id == member_id,
            )) is None
        after = await client.get("/api/v1/workspace/members/details", headers=headers)
        assert after.status_code == 200, after.text
        assert str(member_id) not in {item["userId"] for item in after.json()}
