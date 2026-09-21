"""Workspace suspension must count usable admins, not suspended/disabled admins."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from northstar_api.models import WorkspaceRole
from northstar_api.modules.workspace.services import admin_availability, member_lifecycle
from northstar_api.services.workspace_members import WorkspaceMemberError


async def test_available_admin_count_is_tenant_scoped_and_ignores_unusable_accounts() -> None:
    session = AsyncMock()
    session.scalar.return_value = 2
    tenant_id, workspace_id = uuid4(), uuid4()
    result = await admin_availability.available_workspace_admin_count(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
    )
    assert result == 2
    sql = str(session.scalar.await_args.args[0].compile()).lower()
    assert "workspace_memberships.tenant_id" in sql
    assert "workspace_memberships.workspace_id" in sql
    assert "users.is_active is true" in sql
    assert "workspace_member_states.tenant_id" in sql
    assert "workspace_member_states.workspace_id" in sql
    assert "workspace_member_states.suspended_at is not null" in sql
    assert "workspace_member_states.user_id = workspace_memberships.user_id" in sql
    assert "not (exists" in sql or "not exists" in sql


@pytest.mark.parametrize("available", [0, 1])
async def test_last_available_admin_cannot_be_suspended(monkeypatch, available: int) -> None:
    monkeypatch.setattr(member_lifecycle, "locked_workspace", AsyncMock())
    monkeypatch.setattr(member_lifecycle, "protect_workspace_owner", AsyncMock())
    count = AsyncMock(return_value=available)
    monkeypatch.setattr(member_lifecycle, "available_workspace_admin_count", count)
    audit = Mock()
    monkeypatch.setattr(member_lifecycle, "record_audit_event", audit)
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(role=WorkspaceRole.ADMIN)
    session.get.return_value = None
    with pytest.raises(WorkspaceMemberError) as exc:
        await member_lifecycle.set_member_suspended(
            session, tenant_id=uuid4(), workspace_id=uuid4(),
            actor_user_id=uuid4(), member_user_id=uuid4(),
            suspended=True, reason="Security access review",
        )
    assert exc.value.status_code == 409
    count.assert_awaited_once()
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
    audit.assert_not_called()


async def test_suspending_admin_when_another_is_available_preserves_audit(monkeypatch) -> None:
    monkeypatch.setattr(member_lifecycle, "locked_workspace", AsyncMock())
    monkeypatch.setattr(member_lifecycle, "protect_workspace_owner", AsyncMock())
    count = AsyncMock(return_value=2)
    monkeypatch.setattr(member_lifecycle, "available_workspace_admin_count", count)
    audit = Mock()
    monkeypatch.setattr(member_lifecycle, "record_audit_event", audit)
    publish = Mock(return_value=SimpleNamespace(workspace_id=None))
    monkeypatch.setattr(member_lifecycle, "enqueue_event", publish)
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(role=WorkspaceRole.ADMIN)
    session.get.return_value = None
    workspace_id = uuid4()
    result = await member_lifecycle.set_member_suspended(
        session, tenant_id=uuid4(), workspace_id=workspace_id,
        actor_user_id=uuid4(), member_user_id=uuid4(),
        suspended=True, reason="Security access review",
    )
    assert result is True
    count.assert_awaited_once()
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    audit.assert_called_once()
    event = publish.return_value
    assert event.workspace_id == workspace_id


async def test_suspending_non_admin_does_not_need_admin_count(monkeypatch) -> None:
    monkeypatch.setattr(member_lifecycle, "locked_workspace", AsyncMock())
    monkeypatch.setattr(member_lifecycle, "protect_workspace_owner", AsyncMock())
    count = AsyncMock(side_effect=AssertionError("unnecessary admin count"))
    monkeypatch.setattr(member_lifecycle, "available_workspace_admin_count", count)
    monkeypatch.setattr(member_lifecycle, "record_audit_event", Mock())
    monkeypatch.setattr(member_lifecycle, "enqueue_event", Mock(return_value=SimpleNamespace(workspace_id=None)))
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(role=WorkspaceRole.VIEWER)
    session.get.return_value = None
    assert await member_lifecycle.set_member_suspended(
        session, tenant_id=uuid4(), workspace_id=uuid4(),
        actor_user_id=uuid4(), member_user_id=uuid4(),
        suspended=True, reason="Security access review",
    ) is True
    count.assert_not_awaited()
