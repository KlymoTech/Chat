"""Disabled-account cleanup uses existing scoped member DELETE, never account deletion."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient


async def test_disabled_member_can_be_removed_without_deleting_global_account(
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
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}
    email = f"disabled-cleanup-{uuid4().hex}@example.com"
    invitation = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": email, "role": "viewer", "allAgentsAccess": True, "agentIds": [],
    })
    assert invitation.status_code == 201, invitation.text
    assert delivered
    signup = await client.post("/api/v1/workspace-invitations/signup", json={
        "token": delivered.pop(), "name": "Disabled cleanup target",
        "password": "Disabled-Cleanup-Password-42!", "termsAccepted": True,
        "privacyAccepted": True,
    })
    assert signup.status_code == 201, signup.text
    member_id = UUID(signup.json()["user"]["id"])
    try:
        async with SessionFactory() as session:
            account = await session.get(User, member_id)
            assert account is not None
            account.is_active = False
            await session.commit()

        visible = await client.get("/api/v1/workspace/members/details", headers=headers)
        assert visible.status_code == 200, visible.text
        assert next(row for row in visible.json() if row["userId"] == str(member_id))["status"] == "disabled"
        removed = await client.delete(f"/api/v1/workspace/members/{member_id}", headers=headers)
        assert removed.status_code == 204, removed.text
        details = await client.get("/api/v1/workspace/members/details", headers=headers)
        assert details.status_code == 200, details.text
        assert str(member_id) not in {row["userId"] for row in details.json()}
        async with SessionFactory() as session:
            account = await session.get(User, member_id)
            assert account is not None  # Removal is only from this Workspace.
            assert account.is_active is False
    finally:
        async with SessionFactory() as session:
            account = await session.get(User, member_id)
            if account is not None and not account.is_active:
                account.is_active = True
                await session.commit()
