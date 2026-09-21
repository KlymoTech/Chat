"""An orphan workspace membership cannot count as a usable administrator."""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from northstar_api.modules.workspace.services.admin_availability import available_workspace_admin_count


async def test_available_admin_requires_matching_tenant_membership() -> None:
    session = AsyncMock()
    session.scalar.return_value = None
    assert await available_workspace_admin_count(
        session, tenant_id=uuid4(), workspace_id=uuid4(),
    ) == 0
    sql = str(session.scalar.await_args.args[0].compile()).lower()
    assert "join tenant_memberships on" in sql
    assert "tenant_memberships.user_id = workspace_memberships.user_id" in sql
    assert "tenant_memberships.tenant_id" in sql
    assert "workspace_memberships.tenant_id" in sql
    assert "workspace_memberships.workspace_id" in sql
