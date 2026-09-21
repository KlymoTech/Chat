"""Stale invitations must not reassign an existing member's Workspace access."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_stale_invitation_resend_and_acceptance_preserve_current_member_access(
    client: AsyncClient, auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from northstar_api.database import SessionFactory
    from northstar_api.models import (
        Role, TenantMembership, User, WorkspaceMembership, WorkspaceRole,
    )
    from northstar_api.services.workspace_invitations import (
        WorkspaceInvitationError, accept_workspace_invitation,
    )
    from northstar_api.workspace_invitations import WorkspaceInvitation, WorkspaceInvitationStatus

    captured_tokens: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        captured_tokens.append(kwargs["raw_token"])

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        capture_invitation,
    )
    selected = await client.get("/api/v1/workspace", headers=auth_headers)
    assert selected.status_code == 200, selected.text
    workspace_id = UUID(selected.json()["id"])
    tenant_id = UUID(selected.json()["tenantId"])
    headers = {**auth_headers, "X-Workspace-ID": str(workspace_id)}
    email = f"stale-{uuid4().hex}@example.test"
    created = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": email, "role": "viewer", "allAgentsAccess": False,
        "agentIds": [],
    })
    assert created.status_code == 201, created.text
    assert captured_tokens
    invitation_id = UUID(created.json()["id"])
    token = captured_tokens.pop()

    async with SessionFactory() as session:
        user = User(
            email=email, name="Already joined member",
            password_hash="test-only-unused-password-hash", is_active=True,
        )
        session.add(user)
        await session.flush()
        member_id = user.id
        session.add(TenantMembership(
            tenant_id=tenant_id, user_id=member_id, role=Role.MEMBER,
        ))
        session.add(WorkspaceMembership(
            tenant_id=tenant_id, workspace_id=workspace_id,
            user_id=member_id, role=WorkspaceRole.ADMIN,
            all_agents_access=True,
        ))
        await session.commit()
        original = await session.get(WorkspaceInvitation, invitation_id)
        assert original is not None
        original_hash = original.token_hash
        assert original.status is WorkspaceInvitationStatus.PENDING

    resent = await client.post(
        f"/api/v1/workspace/invitations/{invitation_id}/resend", headers=headers,
    )
    assert resent.status_code == 409, resent.text
    assert "already a member" in resent.json()["detail"]
    assert not captured_tokens

    async with SessionFactory() as session:
        with pytest.raises(WorkspaceInvitationError) as raised:
            await accept_workspace_invitation(
                session, raw_token=token, user_id=member_id,
            )
        assert raised.value.status_code == 409
        await session.rollback()
        invitation = await session.get(WorkspaceInvitation, invitation_id)
        member = await session.get(WorkspaceMembership, (workspace_id, member_id))
        assert invitation is not None and member is not None
        assert invitation.token_hash == original_hash
        assert invitation.status is WorkspaceInvitationStatus.PENDING
        assert member.role is WorkspaceRole.ADMIN
        assert member.all_agents_access is True
