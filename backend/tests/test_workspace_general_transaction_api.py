"""A failed General Settings transaction must not partially persist changes."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import OutboxEvent, Workspace
from northstar_api.routers import workspace as workspace_router


async def test_general_settings_rollback_keeps_workspace_audit_and_outbox_atomic(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    before = await client.get("/api/v1/workspace", headers=auth_headers)
    assert before.status_code == 200, before.text
    previous = before.json()
    tenant_id, workspace_id = UUID(previous["tenantId"]), UUID(previous["id"])

    async def snapshot() -> tuple[str, set[UUID], set[UUID]]:
        async with SessionFactory() as session:
            workspace = await session.get(Workspace, workspace_id)
            assert workspace is not None
            audits = set(await session.scalars(select(IntegrationAuditEvent.id).where(
                IntegrationAuditEvent.tenant_id == tenant_id,
                IntegrationAuditEvent.workspace_id == workspace_id,
                IntegrationAuditEvent.action == "workspace.settings.updated",
            )))
            events = set(await session.scalars(select(OutboxEvent.id).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.event_type == "workspace.settings.updated.v1",
            )))
            return workspace.name, audits, events

    original_state = await snapshot()
    original_recorder = workspace_router.record_general_settings_update

    def fail_after_staging(*args, **kwargs):
        original_recorder(*args, **kwargs)
        raise HTTPException(status_code=503, detail="Simulated transaction failure")

    monkeypatch.setattr(workspace_router, "record_general_settings_update", fail_after_staging)
    failed = await client.patch(
        "/api/v1/workspace", headers=auth_headers,
        json={"name": f"Uncommitted {uuid4().hex[:12]}"},
    )
    assert failed.status_code == 503, failed.text
    monkeypatch.setattr(workspace_router, "record_general_settings_update", original_recorder)

    assert await snapshot() == original_state
    unchanged = await client.get("/api/v1/workspace", headers=auth_headers)
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["name"] == previous["name"]
