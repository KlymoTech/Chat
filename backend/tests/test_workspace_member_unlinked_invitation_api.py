"""Even a just-accepted invitation is not proof without the current link."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient


async def test_unlinked_recent_invitation_cannot_claim_current_membership(
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
    issued = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": f"unlinked-origin-{uuid4().hex}@example.com",
        "role": "viewer", "allAgentsAccess": True, "agentIds": [],
    })
    assert issued.status_code == 201, issued.text
    assert delivered
    signup = await client.post("/api/v1/workspace-invitations/signup", json={
        "token": delivered.pop(), "name": "Unlinked member",
        "password": "Unlinked-Member-Password-42!", "termsAccepted": True,
        "privacyAccepted": True,
    })
    assert signup.status_code == 201, signup.text
    member_id = UUID(signup.json()["user"]["id"])
    try:
        async with SessionFactory() as session:
            origin = await session.get(WorkspaceMemberInvitationOrigin, (UUID(workspace_id), member_id))
            assert origin is not None
            await session.delete(origin)  # Simulate a pre-migration membership with no verified link.
            await session.commit()
        details = await client.get("/api/v1/workspace/members/details", headers=headers)
        assert details.status_code == 200, details.text
        member = next(item for item in details.json() if item["userId"] == str(member_id))
        assert member["invitedByUserId"] is None  # Do not fall back to recent timestamps.
    finally:
        removed = await client.delete(f"/api/v1/workspace/members/{member_id}", headers=headers)
        assert removed.status_code == 204, removed.text
