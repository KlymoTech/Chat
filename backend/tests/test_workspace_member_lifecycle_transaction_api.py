"""Workspace lifecycle state, audit and outbox must commit or roll back together."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import (
    OutboxEvent, Role, TenantMembership, User, WorkspaceMembership, WorkspaceRole,
)
from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState
from northstar_api.modules.workspace.services import member_lifecycle


async def test_failed_suspension_rolls_back_state_and_audit_outbox(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    created = await client.post(
        "/api/v1/workspaces", headers=auth_headers,
        json={"name": "Member rollback regression", "slug": f"member-rollback-{uuid4().hex[:16]}"},
    )
    assert created.status_code == 201, created.text
    tenant_id, workspace_id = UUID(created.json()["tenantId"]), UUID(created.json()["id"])
    headers = {**auth_headers, "X-Workspace-ID": str(workspace_id)}
    target_id = uuid4()
    async with SessionFactory() as session:
        session.add(User(
            id=target_id, name="Rollback member", email=f"rollback-member-{uuid4().hex}@example.com",
            password_hash="test-only-login-disabled", is_active=True,
        ))
        session.add(TenantMembership(tenant_id=tenant_id, user_id=target_id, role=Role.MEMBER))
        session.add(WorkspaceMembership(
            tenant_id=tenant_id, workspace_id=workspace_id, user_id=target_id,
            role=WorkspaceRole.OPERATOR, all_agents_access=True,
        ))
        await session.commit()

    async def snapshot() -> tuple[bool, set[UUID], set[UUID]]:
        async with SessionFactory() as session:
            state = await session.get(WorkspaceMemberState, (workspace_id, target_id))
            audits = set(await session.scalars(select(IntegrationAuditEvent.id).where(
                IntegrationAuditEvent.tenant_id == tenant_id,
                IntegrationAuditEvent.workspace_id == workspace_id,
                IntegrationAuditEvent.action == "workspace.member.suspended",
            )))
            events = set(await session.scalars(select(OutboxEvent.id).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.event_type == "workspace.member.suspended.v1",
            )))
            return state is not None and state.suspended_at is not None, audits, events

    original = await snapshot()
    real_enqueue = member_lifecycle.enqueue_event

    def fail_after_staging(*args, **kwargs):
        real_enqueue(*args, **kwargs)
        raise HTTPException(status_code=503, detail="Simulated lifecycle transaction failure")

    monkeypatch.setattr(member_lifecycle, "enqueue_event", fail_after_staging)
    try:
        failed = await client.post(
            f"/api/v1/workspace/members/{target_id}/suspend", headers=headers,
            json={"reason": "Rollback check", "confirmation": "SUSPEND"},
        )
    finally:
        monkeypatch.setattr(member_lifecycle, "enqueue_event", real_enqueue)
    assert failed.status_code == 503, failed.text
    assert await snapshot() == original

    succeeded = await client.post(
        f"/api/v1/workspace/members/{target_id}/suspend", headers=headers,
        json={"reason": "Approved access review", "confirmation": "SUSPEND"},
    )
    assert succeeded.status_code == 200, succeeded.text
    once = await snapshot()
    assert once[0] is True
    assert len(once[1] - original[1]) == 1
    assert len(once[2] - original[2]) == 1

    repeated = await client.post(
        f"/api/v1/workspace/members/{target_id}/suspend", headers=headers,
        json={"reason": "Repeated administrative request", "confirmation": "SUSPEND"},
    )
    assert repeated.status_code == 200, repeated.text
    assert await snapshot() == once
