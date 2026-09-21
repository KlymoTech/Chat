"""HTTP-to-database regression test for workspace general settings changes."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import OutboxEvent


async def test_workspace_general_settings_persist_with_scoped_audit_and_outbox(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    original = current.json()
    workspace_id = UUID(original["id"])
    tenant_id = UUID(original["tenantId"])
    name = f"General Settings {uuid4().hex[:12]}"

    async def snapshots() -> tuple[list[IntegrationAuditEvent], list[OutboxEvent]]:
        async with SessionFactory() as session:
            audits = list(await session.scalars(select(IntegrationAuditEvent).where(
                IntegrationAuditEvent.tenant_id == tenant_id,
                IntegrationAuditEvent.workspace_id == workspace_id,
                IntegrationAuditEvent.action == "workspace.settings.updated",
            )))
            events = list(await session.scalars(select(OutboxEvent).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.event_type == "workspace.settings.updated.v1",
            )))
            return audits, events

    initial_audits, initial_events = await snapshots()
    before_audit_ids = {item.id for item in initial_audits}
    before_event_ids = {item.id for item in initial_events}
    try:
        updated = await client.patch("/api/v1/workspace", headers=auth_headers, json={"name": name})
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == name
        persisted = await client.get("/api/v1/workspace", headers=auth_headers)
        assert persisted.status_code == 200, persisted.text
        assert persisted.json()["name"] == name

        audits, events = await snapshots()
        new_audits = [item for item in audits if item.id not in before_audit_ids]
        new_events = [item for item in events if item.id not in before_event_ids]
        assert len(new_audits) == 1
        assert len(new_events) == 1
        assert new_audits[0].metadata_json == {"fields": ["name"]}
        assert new_audits[0].tenant_id == tenant_id
        assert new_audits[0].workspace_id == workspace_id
        assert new_events[0].payload == {"workspaceId": str(workspace_id), "fields": ["name"]}

        repeated = await client.patch("/api/v1/workspace", headers=auth_headers, json={"name": name})
        assert repeated.status_code == 200, repeated.text
        repeat_audits, repeat_events = await snapshots()
        assert {item.id for item in repeat_audits} == {item.id for item in audits}
        assert {item.id for item in repeat_events} == {item.id for item in events}
    finally:
        restored = await client.patch(
            "/api/v1/workspace", headers=auth_headers, json={"name": original["name"]},
        )
        assert restored.status_code == 200, restored.text
