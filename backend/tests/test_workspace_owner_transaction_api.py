"""A failed workspace ownership handover must not partially persist owner/audit/outbox."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import (
    OutboxEvent, Role, TenantMembership, User, Workspace,
    WorkspaceMembership, WorkspaceRole,
)
from northstar_api.modules.workspace.services import ownership


async def test_failed_owner_transfer_rolls_back_owner_and_audit_outbox(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    created = await client.post(
        "/api/v1/workspaces", headers=auth_headers,
        json={"name": "Owner rollback regression", "slug": f"owner-rollback-{uuid4().hex[:16]}"},
    )
    assert created.status_code == 201, created.text
    tenant_id, workspace_id = UUID(created.json()["tenantId"]), UUID(created.json()["id"])
    headers = {**auth_headers, "X-Workspace-ID": str(workspace_id)}
    previous = await client.get("/api/v1/workspace/owner", headers=headers)
    assert previous.status_code == 200, previous.text
    initial_owner_id = previous.json()["ownerUserId"]
    assert initial_owner_id is not None

    target_id = uuid4()
    async with SessionFactory() as session:
        session.add(User(
            id=target_id, name="Rollback target", email=f"rollback-owner-{uuid4().hex}@example.com",
            password_hash="test-only-login-disabled", is_active=True,
        ))
        session.add(TenantMembership(tenant_id=tenant_id, user_id=target_id, role=Role.MEMBER))
        session.add(WorkspaceMembership(
            tenant_id=tenant_id, workspace_id=workspace_id, user_id=target_id,
            role=WorkspaceRole.ADMIN, all_agents_access=True,
        ))
        await session.commit()

    async def snapshot() -> tuple[dict, set[UUID], set[UUID]]:
        async with SessionFactory() as session:
            workspace = await session.get(Workspace, workspace_id)
            assert workspace is not None
            audits = set(await session.scalars(select(IntegrationAuditEvent.id).where(
                IntegrationAuditEvent.tenant_id == tenant_id,
                IntegrationAuditEvent.workspace_id == workspace_id,
                IntegrationAuditEvent.action == "workspace.owner.transferred",
            )))
            events = set(await session.scalars(select(OutboxEvent.id).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.event_type == "workspace.owner.transferred.v1",
            )))
            return dict(workspace.settings_json or {}), audits, events

    original = await snapshot()
    real_enqueue = ownership.enqueue_event

    def fail_after_staging(*args, **kwargs):
        real_enqueue(*args, **kwargs)
        raise HTTPException(status_code=503, detail="Simulated owner transaction failure")

    monkeypatch.setattr(ownership, "enqueue_event", fail_after_staging)
    try:
        response = await client.post(
            "/api/v1/workspace/owner/transfer", headers=headers,
            json={
                "expectedOwnerUserId": initial_owner_id,
                "targetUserId": str(target_id),
                "reason": "administrative_handover", "confirmation": "TRANSFER",
            },
        )
    finally:
        monkeypatch.setattr(ownership, "enqueue_event", real_enqueue)
    assert response.status_code == 503, response.text
    assert await snapshot() == original
    reread = await client.get("/api/v1/workspace/owner", headers=headers)
    assert reread.status_code == 200, reread.text
    assert reread.json()["ownerUserId"] == initial_owner_id
