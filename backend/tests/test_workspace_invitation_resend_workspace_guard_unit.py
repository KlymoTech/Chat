"""Invitation resend must not rotate credentials for archived or foreign Workspaces."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from northstar_api.email_config import EmailSettings
from northstar_api.models import WorkspaceRole, WorkspaceStatus
from northstar_api.services import workspace_invitations as service
from northstar_api.workspace_invitations import WorkspaceInvitationStatus


@pytest.mark.asyncio
async def test_resend_rejects_missing_archived_or_foreign_workspace_before_loading_invitation() -> None:
    tenant_id, workspace_id = uuid4(), uuid4()
    session = AsyncMock()
    # An archived or cross-tenant Workspace is excluded by the initial query.
    session.scalar.return_value = None
    with pytest.raises(service.WorkspaceInvitationError) as raised:
        await service.resend_workspace_invitation(
            session, tenant_id=tenant_id, workspace_id=workspace_id,
            invitation_id=uuid4(), invited_by_user_id=uuid4(),
            settings=EmailSettings(),
        )
    assert raised.value.status_code == 404
    assert session.scalar.await_count == 1
    statement = session.scalar.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert 'workspaces.status' in sql and 'FOR UPDATE' in sql
    assert tenant_id in statement.compile().params.values()
    assert workspace_id in statement.compile().params.values()
    assert WorkspaceStatus.ACTIVE in statement.compile().params.values()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_resend_locks_workspace_before_invitation_and_rotates_only_valid_invitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, workspace_id, invitation_id, actor_id = (uuid4() for _ in range(4))
    invitation = SimpleNamespace(
        id=invitation_id, tenant_id=tenant_id, workspace_id=workspace_id,
        role=WorkspaceRole.VIEWER, all_agents_access=True,
        status=WorkspaceInvitationStatus.PENDING, token_hash='a' * 64,
        invited_by_user_id=None, expires_at=None, last_delivery_error='OldFailure',
        updated_at=None,
    )
    session = AsyncMock()
    session.scalar.side_effect = [SimpleNamespace(id=workspace_id), invitation]
    audit = Mock()
    monkeypatch.setattr(service, 'stage_invitation_transition', audit)
    monkeypatch.setattr(service.secrets, 'token_urlsafe', lambda _size: 'replacement-token')
    issued = await service.resend_workspace_invitation(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
        invitation_id=invitation_id, invited_by_user_id=actor_id,
        settings=EmailSettings(),
    )
    assert issued.invitation is invitation and issued.token == 'replacement-token'
    assert invitation.token_hash == service.workspace_invitation_token_hash(issued.token)
    assert invitation.invited_by_user_id == actor_id
    assert invitation.last_delivery_error is None
    assert session.scalar.await_count == 2
    workspace_sql = str(session.scalar.await_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    invitation_sql = str(session.scalar.await_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    assert 'FROM workspaces' in workspace_sql and 'FOR UPDATE' in workspace_sql
    assert 'FROM workspace_invitations' in invitation_sql and 'FOR UPDATE' in invitation_sql
    audit.assert_called_once()
    session.flush.assert_awaited_once()
