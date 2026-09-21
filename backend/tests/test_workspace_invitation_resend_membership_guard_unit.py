"""Stale invitation resends cannot target an existing member of the selected Workspace."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from sqlalchemy.dialects import postgresql

from northstar_api.modules.workspace.services.invitation_resend_membership_guard import (
    prevent_resend_to_existing_workspace_member as check,
)


def _request(invitation_id: str, *, method: str = "POST", route: str | None = None) -> Request:
    path = route or "/api/v1/workspace/invitations/{invitation_id}/resend"
    return Request({
        "type": "http", "method": method, "path": path,
        "headers": [], "query_string": b"",
        "route": SimpleNamespace(path=path),
        "path_params": {"invitation_id": invitation_id},
    })


@pytest.mark.asyncio
async def test_resend_rejects_a_scoped_existing_member_without_mutation() -> None:
    tenant_id, workspace_id, invitation_id, member_id = (uuid4() for _ in range(4))
    session = AsyncMock()
    session.scalar.side_effect = ["member@example.test", member_id]
    principal = SimpleNamespace(
        tenant_id=tenant_id, workspace_id=workspace_id,
        permissions=frozenset({"members.manage"}),
    )
    with pytest.raises(HTTPException) as raised:
        await check(_request(str(invitation_id)), principal, session)
    assert raised.value.status_code == 409
    assert raised.value.detail == "This email address is already a member of the workspace"
    assert session.scalar.await_count == 2
    invitation_query, member_query = (call.args[0] for call in session.scalar.await_args_list)
    invitation_sql = str(invitation_query.compile(dialect=postgresql.dialect()))
    member_sql = str(member_query.compile(dialect=postgresql.dialect()))
    assert "workspace_invitations.tenant_id" in invitation_sql
    assert "workspace_invitations.workspace_id" in invitation_sql
    assert "workspace_memberships.tenant_id" in member_sql
    assert "workspace_memberships.workspace_id" in member_sql
    assert "lower(users.email)" in member_sql
    assert {tenant_id, workspace_id, invitation_id} <= set(invitation_query.compile().params.values())
    assert {tenant_id, workspace_id, "member@example.test"} <= set(member_query.compile().params.values())
    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_resend_without_existing_member_preserves_existing_service_path() -> None:
    tenant_id, workspace_id, invitation_id = (uuid4() for _ in range(3))
    session = AsyncMock()
    session.scalar.side_effect = ["new@example.test", None]
    await check(
        _request(str(invitation_id)),
        SimpleNamespace(tenant_id=tenant_id, workspace_id=workspace_id,
                        permissions=frozenset({"members.manage"})),
        session,
    )
    assert session.scalar.await_count == 2
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,route,permissions", [
    ("GET", "/api/v1/workspace/invitations", frozenset({"members.manage"})),
    ("POST", "/api/v1/workspace/invitations", frozenset({"members.manage"})),
    ("POST", "/api/v1/workspace/invitations/{invitation_id}/resend", frozenset({"members.view"})),
    ("POST", "/api/v1/workspace-invitations/signup", frozenset({"members.manage"})),
])
async def test_guard_avoids_other_routes_and_unauthorized_database_lookups(
    method: str, route: str, permissions: frozenset[str],
) -> None:
    session = AsyncMock()
    await check(
        _request(str(uuid4()), method=method, route=route),
        SimpleNamespace(tenant_id=uuid4(), workspace_id=uuid4(), permissions=permissions),
        session,
    )
    session.scalar.assert_not_awaited()
