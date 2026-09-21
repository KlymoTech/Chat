"""Workspace reactivation must not misreport access for globally disabled users."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient


async def test_disabled_account_cannot_be_reactivated_until_account_is_restored(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    from northstar_api.database import SessionFactory
    from northstar_api.models import User
    from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState

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
    invitation = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": f"disabled-reactivation-{uuid4().hex}@example.com",
        "role": "viewer", "allAgentsAccess": True, "agentIds": [],
    })
    assert invitation.status_code == 201, invitation.text
    assert delivered
    signup = await client.post("/api/v1/workspace-invitations/signup", json={
        "token": delivered.pop(), "name": "Disabled reactivation member",
        "password": "Disabled-Reactivation-Password-42!", "termsAccepted": True,
        "privacyAccepted": True,
    })
    assert signup.status_code == 201, signup.text
    member_id = UUID(signup.json()["user"]["id"])
    endpoint = f"/api/v1/workspace/members/{member_id}/reactivate"
    try:
        suspended = await client.post(
            f"/api/v1/workspace/members/{member_id}/suspend", headers=headers,
            json={"reason": "Access review", "confirmation": "SUSPEND"},
        )
        assert suspended.status_code == 200, suspended.text
        async with SessionFactory() as session:
            user = await session.get(User, member_id)
            assert user is not None
            user.is_active = False
            await session.commit()

        blocked = await client.post(endpoint, headers=headers, json={
            "reason": "Attempted workspace restore", "confirmation": "REACTIVATE",
        })
        assert blocked.status_code == 409, blocked.text
        assert "disabled" in blocked.text.lower()
        async with SessionFactory() as session:
            state = await session.get(WorkspaceMemberState, (UUID(workspace_id), member_id))
            assert state is not None and state.suspended_at is not None
            user = await session.get(User, member_id)
            assert user is not None and user.is_active is False
            user.is_active = True
            await session.commit()

        restored = await client.post(endpoint, headers=headers, json={
            "reason": "Account restored after access review", "confirmation": "REACTIVATE",
        })
        assert restored.status_code == 200, restored.text
        assert restored.json() == {"userId": str(member_id), "status": "active"}
        async with SessionFactory() as session:
            state = await session.get(WorkspaceMemberState, (UUID(workspace_id), member_id))
            assert state is not None and state.suspended_at is None
    finally:
        async with SessionFactory() as session:
            user = await session.get(User, member_id)
            if user is not None and not user.is_active:
                user.is_active = True
                await session.commit()
        removed = await client.delete(f"/api/v1/workspace/members/{member_id}", headers=headers)
        assert removed.status_code == 204, removed.text
