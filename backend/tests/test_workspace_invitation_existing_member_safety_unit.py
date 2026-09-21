"""An old invite is not authority to change an existing Workspace member's access."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from northstar_api.email_config import EmailSettings
from northstar_api.models import Role, WorkspaceRole
from northstar_api.services import workspace_invitations as service
from northstar_api.workspace_invitations import WorkspaceInvitationStatus


def _pending_invitation(*, tenant_id, workspace_id, invitation_id):
    return SimpleNamespace(
        id=invitation_id, tenant_id=tenant_id, workspace_id=workspace_id,
        email="member@example.test", status=WorkspaceInvitationStatus.PENDING,
        role=WorkspaceRole.VIEWER, all_agents_access=False,
        token_hash="original-hash", invited_by_user_id=None,
        expires_at=None, last_delivery_error=None, updated_at=None,
    )


@pytest.mark.asyncio
async def test_stale_resend_rejected_inside_service_after_workspace_and_invitation_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, workspace_id, invitation_id, actor_id, member_id = (
        uuid4() for _ in range(5)
    )
    invitation = _pending_invitation(
        tenant_id=tenant_id, workspace_id=workspace_id,
        invitation_id=invitation_id,
    )
    session = AsyncMock()
    session.scalar.side_effect = [SimpleNamespace(id=workspace_id), invitation, member_id]
    audit = Mock()
    token_generator = Mock(side_effect=AssertionError("stale invite must not rotate"))
    monkeypatch.setattr(service, "stage_invitation_transition", audit)
    monkeypatch.setattr(service.secrets, "token_urlsafe", token_generator)
    with pytest.raises(service.WorkspaceInvitationError) as raised:
        await service.resend_workspace_invitation(
            session, tenant_id=tenant_id, workspace_id=workspace_id,
            invitation_id=invitation_id, invited_by_user_id=actor_id,
            settings=EmailSettings(_env_file=None, email_delivery_mode="log"),
        )
    assert raised.value.status_code == 409
    assert session.scalar.await_count == 3
    scoped_member_query = session.scalar.await_args_list[2].args[0]
    compiled = scoped_member_query.compile(dialect=postgresql.dialect())
    assert "workspace_memberships.tenant_id" in str(compiled)
    assert "workspace_memberships.workspace_id" in str(compiled)
    assert {tenant_id, workspace_id, invitation.email} <= set(scoped_member_query.compile().params.values())
    assert invitation.token_hash == "original-hash"
    assert invitation.status is WorkspaceInvitationStatus.PENDING
    assert invitation.invited_by_user_id is None
    token_generator.assert_not_called()
    audit.assert_not_called()
    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_acceptance_never_overwrites_role_or_agent_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, workspace_id, invitation_id, member_id = (uuid4() for _ in range(4))
    invitation = _pending_invitation(
        tenant_id=tenant_id, workspace_id=workspace_id,
        invitation_id=invitation_id,
    )
    original_member = SimpleNamespace(
        role=WorkspaceRole.ADMIN, all_agents_access=True,
        updated_at=None,
    )
    session = AsyncMock()
    session.scalar.side_effect = [SimpleNamespace(role=Role.MEMBER), original_member]
    set_tenant = AsyncMock()
    replace_access = AsyncMock()
    audit = Mock()
    monkeypatch.setattr(service, "set_tenant_context", set_tenant)
    monkeypatch.setattr(service, "replace_member_agent_access", replace_access)
    monkeypatch.setattr(service, "stage_invitation_transition", audit)
    details = service.WorkspaceInvitationDetails(
        invitation=invitation,
        tenant=SimpleNamespace(id=tenant_id),
        workspace=SimpleNamespace(id=workspace_id),
        agent_ids=(), existing_user=True,
    )
    user = SimpleNamespace(id=member_id, email=invitation.email, last_login_at=None)
    with pytest.raises(service.WorkspaceInvitationError) as raised:
        await service._accept_invitation(session, details=details, user=user)
    assert raised.value.status_code == 409
    set_tenant.assert_awaited_once_with(session, tenant_id)
    assert session.scalar.await_count == 2
    assert original_member.role is WorkspaceRole.ADMIN
    assert original_member.all_agents_access is True
    assert original_member.updated_at is None
    assert invitation.status is WorkspaceInvitationStatus.PENDING
    assert invitation.token_hash == "original-hash"
    assert user.last_login_at is None
    replace_access.assert_not_awaited()
    audit.assert_not_called()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
