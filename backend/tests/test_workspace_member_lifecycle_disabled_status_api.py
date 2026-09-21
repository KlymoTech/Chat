"""A globally disabled member must not be presented as active by lifecycle."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient


async def test_disabled_member_lifecycle_is_consistent_and_tenant_scoped(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    from northstar_api.database import SessionFactory
    from northstar_api.models import (
        Role, TenantMembership, User, WorkspaceMembership, WorkspaceRole,
    )
    from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState

    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    tenant_id = UUID(current.json()["tenantId"])
    workspace_id = current.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    member_id = uuid4()
    async with SessionFactory() as session:
        session.add(User(
            id=member_id, name="Globally disabled member",
            email=f"disabled-lifecycle-{uuid4().hex}@example.com",
            password_hash="test-only-disabled-login", is_active=False,
        ))
        session.add(TenantMembership(tenant_id=tenant_id, user_id=member_id, role=Role.MEMBER))
        session.add(WorkspaceMembership(
            tenant_id=tenant_id, workspace_id=UUID(workspace_id), user_id=member_id,
            role=WorkspaceRole.VIEWER, all_agents_access=True,
        ))
        await session.commit()

    try:
        lifecycle = await client.get("/api/v1/workspace/members/lifecycle", headers=headers)
        assert lifecycle.status_code == 200, lifecycle.text
        state = next(item for item in lifecycle.json() if item["userId"] == str(member_id))
        assert state["status"] == "disabled"
        details = await client.get("/api/v1/workspace/members/details", headers=headers)
        assert details.status_code == 200, details.text
        detail = next(item for item in details.json() if item["userId"] == str(member_id))
        assert detail["status"] == state["status"]

        suspended = await client.post(
            f"/api/v1/workspace/members/{member_id}/suspend", headers=headers,
            json={"reason": "Preserve suspension after account restore", "confirmation": "SUSPEND"},
        )
        assert suspended.status_code == 200, suspended.text
        assert suspended.json() == {"userId": str(member_id), "status": "disabled"}
        async with SessionFactory() as session:
            workspace_state = await session.get(WorkspaceMemberState, (UUID(workspace_id), member_id))
            assert workspace_state is not None and workspace_state.suspended_at is not None
        lifecycle_after = await client.get("/api/v1/workspace/members/lifecycle", headers=headers)
        assert lifecycle_after.status_code == 200, lifecycle_after.text
        assert next(item for item in lifecycle_after.json() if item["userId"] == str(member_id))[
            "status"
        ] == "disabled"

        other = await client.post("/api/v1/workspaces", headers=auth_headers, json={
            "name": "Lifecycle status isolation",
            "slug": f"lifecycle-disabled-{uuid4().hex[:12]}",
        })
        assert other.status_code == 201, other.text
        other_lifecycle = await client.get("/api/v1/workspace/members/lifecycle", headers={
            **auth_headers, "X-Workspace-ID": other.json()["id"],
        })
        assert other_lifecycle.status_code == 200, other_lifecycle.text
        assert str(member_id) not in {item["userId"] for item in other_lifecycle.json()}
    finally:
        removed = await client.delete(f"/api/v1/workspace/members/{member_id}", headers=headers)
        assert removed.status_code == 204, removed.text
