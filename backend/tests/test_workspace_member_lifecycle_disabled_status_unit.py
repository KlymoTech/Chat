"""Global disablement must override Workspace-only status without leaking tenants."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from northstar_api.modules.workspace.services.member_lifecycle import member_statuses


async def test_disabled_account_overrides_suspension_and_query_is_workspace_scoped() -> None:
    tenant_id, workspace_id = uuid4(), uuid4()
    active_id, suspended_id, disabled_id = uuid4(), uuid4(), uuid4()
    session = AsyncMock()
    session.scalars.side_effect = [
        [SimpleNamespace(user_id=suspended_id, suspended_at=datetime.now(UTC)),
         SimpleNamespace(user_id=disabled_id, suspended_at=datetime.now(UTC))],
        [disabled_id],
    ]
    result = await member_statuses(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
        user_ids=[active_id, suspended_id, disabled_id],
    )
    assert result == {
        active_id: "active", suspended_id: "suspended", disabled_id: "disabled",
    }
    disabled_query = session.scalars.await_args_list[1].args[0]
    sql = str(disabled_query)
    assert "workspace_memberships.tenant_id" in sql
    assert "workspace_memberships.workspace_id" in sql
    assert "users.is_active IS false" in sql
    assert tenant_id in disabled_query.compile().params.values()
    assert workspace_id in disabled_query.compile().params.values()


async def test_empty_lifecycle_does_not_query_database() -> None:
    session = AsyncMock()
    assert await member_statuses(
        session, tenant_id=uuid4(), workspace_id=uuid4(), user_ids=[],
    ) == {}
    session.scalars.assert_not_awaited()
