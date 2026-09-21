"""Role edits/removal must leave a usable administrator, not merely an admin row."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from northstar_api.models import WorkspaceRole
from northstar_api.modules.workspace.services import admin_availability
from northstar_api.services import workspace_members
from northstar_api.services.workspace_members import WorkspaceMemberError


async def test_available_admin_exclusion_keeps_tenant_workspace_filters() -> None:
    session = AsyncMock()
    session.scalar.return_value = 1
    tenant_id, workspace_id, excluded = uuid4(), uuid4(), uuid4()
    assert await admin_availability.available_workspace_admin_count(
        session, tenant_id=tenant_id, workspace_id=workspace_id, exclude_user_id=excluded,
    ) == 1
    statement = session.scalar.await_args.args[0]
    query = str(statement.compile()).lower()
    assert "workspace_memberships.tenant_id" in query
    assert "workspace_memberships.workspace_id" in query
    assert "tenant_memberships.tenant_id" in query
    assert "users.is_active is true" in query
    assert "workspace_member_states.suspended_at is not null" in query
    assert "workspace_memberships.user_id !=" in query
    assert excluded in statement.compile().params.values()


@pytest.mark.parametrize("next_role", [WorkspaceRole.MANAGER, None])
async def test_no_other_usable_admin_denies_demote_or_remove(monkeypatch, next_role) -> None:
    tenant_id, workspace_id, target_id = uuid4(), uuid4(), uuid4()
    session = AsyncMock()
    session.scalar.return_value = workspace_id
    count = AsyncMock(return_value=0)
    monkeypatch.setattr(workspace_members, "available_workspace_admin_count", count)
    with pytest.raises(WorkspaceMemberError) as caught:
        await workspace_members._protect_last_admin(
            session, tenant_id=tenant_id, workspace_id=workspace_id,
            membership=SimpleNamespace(user_id=target_id, role=WorkspaceRole.ADMIN),
            next_role=next_role,
        )
    assert caught.value.status_code == 409
    count.assert_awaited_once_with(
        session, tenant_id=tenant_id, workspace_id=workspace_id, exclude_user_id=target_id,
    )
    assert "workspaces.tenant_id" in str(session.scalar.await_args.args[0].compile()).lower()
    session.flush.assert_not_awaited()
    session.delete.assert_not_awaited()


async def test_other_available_admin_allows_demote(monkeypatch) -> None:
    session = AsyncMock()
    session.scalar.return_value = uuid4()
    count = AsyncMock(return_value=1)
    monkeypatch.setattr(workspace_members, "available_workspace_admin_count", count)
    await workspace_members._protect_last_admin(
        session, tenant_id=uuid4(), workspace_id=uuid4(),
        membership=SimpleNamespace(user_id=uuid4(), role=WorkspaceRole.ADMIN),
        next_role=WorkspaceRole.VIEWER,
    )
    count.assert_awaited_once()


@pytest.mark.parametrize("role,next_role", [
    (WorkspaceRole.VIEWER, None),
    (WorkspaceRole.ADMIN, WorkspaceRole.ADMIN),
])
async def test_non_admin_removal_or_unchanged_admin_role_skips_count(monkeypatch, role, next_role) -> None:
    session = AsyncMock()
    count = AsyncMock(side_effect=AssertionError("Not a removal of administrator status"))
    monkeypatch.setattr(workspace_members, "available_workspace_admin_count", count)
    await workspace_members._protect_last_admin(
        session, tenant_id=uuid4(), workspace_id=uuid4(),
        membership=SimpleNamespace(user_id=uuid4(), role=role), next_role=next_role,
    )
    session.scalar.assert_not_awaited()
    count.assert_not_awaited()


async def test_missing_scoped_workspace_denies_before_count(monkeypatch) -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    count = AsyncMock()
    monkeypatch.setattr(workspace_members, "available_workspace_admin_count", count)
    with pytest.raises(WorkspaceMemberError) as caught:
        await workspace_members._protect_last_admin(
            session, tenant_id=uuid4(), workspace_id=uuid4(),
            membership=SimpleNamespace(user_id=uuid4(), role=WorkspaceRole.ADMIN),
            next_role=None,
        )
    assert caught.value.status_code == 404
    count.assert_not_awaited()
