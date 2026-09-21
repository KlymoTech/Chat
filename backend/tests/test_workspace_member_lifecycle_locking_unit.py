"""Member suspension must follow the ownership/member lock order and fail closed."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from northstar_api.modules.workspace.services import member_lifecycle
from northstar_api.modules.workspace.services.ownership import WorkspaceOwnershipError
from northstar_api.services.workspace_members import WorkspaceMemberError


@pytest.mark.parametrize("suspended", [True, False])
async def test_workspace_lock_precedes_membership_lock(monkeypatch, suspended: bool) -> None:
    order: list[str] = []

    async def lock_workspace(*args, **kwargs) -> object:
        order.append("workspace")
        return object()

    async def protect_owner(*args, **kwargs) -> None:
        order.append("owner")

    async def no_member(*args, **kwargs) -> None:
        order.append("member")
        return None

    monkeypatch.setattr(member_lifecycle, "locked_workspace", lock_workspace)
    monkeypatch.setattr(member_lifecycle, "protect_workspace_owner", protect_owner)
    session = AsyncMock()
    session.scalar.side_effect = no_member
    with pytest.raises(WorkspaceMemberError) as error:
        await member_lifecycle.set_member_suspended(
            session, tenant_id=uuid4(), workspace_id=uuid4(),
            actor_user_id=uuid4(), member_user_id=uuid4(),
            suspended=suspended, reason="Routine access review",
        )
    assert error.value.status_code == 404
    assert order == (["workspace", "owner", "member"] if suspended else ["workspace", "member"])
    session.flush.assert_not_awaited()


async def test_owner_protection_conflict_is_a_member_conflict(monkeypatch) -> None:
    async def lock_workspace(*args, **kwargs) -> object:
        return object()

    async def refuse_owner(*args, **kwargs) -> None:
        raise WorkspaceOwnershipError("Transfer workspace ownership before suspension", 409)

    monkeypatch.setattr(member_lifecycle, "locked_workspace", lock_workspace)
    monkeypatch.setattr(member_lifecycle, "protect_workspace_owner", refuse_owner)
    session = AsyncMock()
    with pytest.raises(WorkspaceMemberError) as error:
        await member_lifecycle.set_member_suspended(
            session, tenant_id=uuid4(), workspace_id=uuid4(),
            actor_user_id=uuid4(), member_user_id=uuid4(),
            suspended=True, reason="Routine access review",
        )
    assert error.value.status_code == 409
    session.scalar.assert_not_awaited()
    session.flush.assert_not_awaited()


async def test_missing_workspace_preserves_not_found(monkeypatch) -> None:
    async def missing_workspace(*args, **kwargs) -> None:
        raise WorkspaceOwnershipError("Workspace not found", 404)

    monkeypatch.setattr(member_lifecycle, "locked_workspace", missing_workspace)
    session = AsyncMock()
    with pytest.raises(WorkspaceMemberError) as error:
        await member_lifecycle.set_member_suspended(
            session, tenant_id=uuid4(), workspace_id=uuid4(),
            actor_user_id=uuid4(), member_user_id=uuid4(),
            suspended=False, reason="Routine access review",
        )
    assert error.value.status_code == 404
    session.scalar.assert_not_awaited()
