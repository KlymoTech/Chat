"""HTTP and database coverage for the additive Workspace general profile."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import OutboxEvent


async def test_extended_general_profile_persists_and_audits_only_field_names(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    original = current.json()
    workspace_id = UUID(original["id"])
    tenant_id = UUID(original["tenantId"])
    profile = dict(original["preferences"])
    profile["industry"] = f"Education-{uuid4().hex[:8]}"
    profile["country"] = "India"
    profile["currency"] = "INR"
    profile["weekStart"] = "sunday"
    profile["businessHours"] = {
        **profile["businessHours"],
        "monday": {"enabled": True, "opens": "08:00", "closes": "18:00"},
    }

    async def snapshots() -> tuple[set[UUID], set[UUID]]:
        async with SessionFactory() as session:
            audits = set(await session.scalars(select(IntegrationAuditEvent.id).where(
                IntegrationAuditEvent.tenant_id == tenant_id,
                IntegrationAuditEvent.workspace_id == workspace_id,
                IntegrationAuditEvent.action == "workspace.settings.updated",
            )))
            outbox = set(await session.scalars(select(OutboxEvent.id).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.event_type == "workspace.settings.updated.v1",
            )))
            return audits, outbox

    previous_audits, previous_events = await snapshots()
    try:
        changed = await client.patch("/api/v1/workspace", headers=auth_headers, json={"preferences": profile})
        assert changed.status_code == 200, changed.text
        assert changed.json()["preferences"]["industry"] == profile["industry"]
        persisted = await client.get("/api/v1/workspace", headers=auth_headers)
        assert persisted.status_code == 200, persisted.text
        assert persisted.json()["preferences"]["businessHours"]["monday"]["opens"] == "08:00"
        assert persisted.json()["preferences"]["currency"] == "INR"

        audits, events = await snapshots()
        assert len(audits - previous_audits) == 1
        assert len(events - previous_events) == 1
        async with SessionFactory() as session:
            audit = await session.get(IntegrationAuditEvent, next(iter(audits - previous_audits)))
            event = await session.get(OutboxEvent, next(iter(events - previous_events)))
            assert audit is not None and event is not None
            assert audit.tenant_id == tenant_id and audit.workspace_id == workspace_id
            assert event.tenant_id == tenant_id and event.workspace_id == workspace_id
            assert audit.metadata_json["fields"] == [
                "business_hours", "country", "currency", "industry", "week_start",
            ]
            assert event.payload["fields"] == audit.metadata_json["fields"]
            assert profile["industry"] not in str(audit.metadata_json)
            assert profile["industry"] not in str(event.payload)

        unchanged = await client.patch("/api/v1/workspace", headers=auth_headers, json={"preferences": profile})
        assert unchanged.status_code == 200, unchanged.text
        assert await snapshots() == (audits, events)
        invalid = await client.patch("/api/v1/workspace", headers=auth_headers, json={
            "preferences": {**profile, "currency": "invalid"},
        })
        assert invalid.status_code == 422, invalid.text
        assert await snapshots() == (audits, events)
    finally:
        restored = await client.patch(
            "/api/v1/workspace", headers=auth_headers,
            json={"preferences": original["preferences"]},
        )
        assert restored.status_code == 200, restored.text
