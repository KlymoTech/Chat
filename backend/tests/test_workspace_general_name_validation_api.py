"""HTTP regressions for validated Workspace names on create and profile PATCH."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import OutboxEvent


async def test_invalid_trimmed_name_does_not_update_workspace_or_emit_general_event(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    before = await client.get("/api/v1/workspace", headers=auth_headers)
    assert before.status_code == 200, before.text
    original = before.json()
    workspace_id, tenant_id = UUID(original["id"]), UUID(original["tenantId"])

    async def event_ids() -> tuple[set[UUID], set[UUID]]:
        async with SessionFactory() as session:
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
            return audits, events

    before_events = await event_ids()
    for invalid in ("   ", " a "):
        rejected = await client.patch(
            "/api/v1/workspace", headers=auth_headers,
            json={"name": invalid, "preferences": {"industry": "Must not persist"}},
        )
        assert rejected.status_code == 422, rejected.text
    after = await client.get("/api/v1/workspace", headers=auth_headers)
    assert after.status_code == 200, after.text
    assert after.json()["name"] == original["name"]
    assert after.json()["preferences"] == original["preferences"]
    assert await event_ids() == before_events


async def test_workspace_creation_rejects_empty_normalized_name(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    slug = f"invalid-name-{uuid4().hex[:16]}"
    rejected = await client.post(
        "/api/v1/workspaces", headers=auth_headers,
        json={"name": "   ", "slug": slug},
    )
    assert rejected.status_code == 422, rejected.text
    listed = await client.get("/api/v1/workspaces", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert all(item["slug"] != slug for item in listed.json())


async def test_valid_name_is_trimmed_on_patch_and_read_back(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    before = await client.get("/api/v1/workspace", headers=auth_headers)
    assert before.status_code == 200, before.text
    original = before.json()
    name = f"Trimmed {uuid4().hex[:12]}"
    try:
        saved = await client.patch("/api/v1/workspace", headers=auth_headers, json={"name": f"  {name}  "})
        assert saved.status_code == 200, saved.text
        assert saved.json()["name"] == name
        reread = await client.get("/api/v1/workspace", headers=auth_headers)
        assert reread.status_code == 200, reread.text
        assert reread.json()["name"] == name
    finally:
        restored = await client.patch(
            "/api/v1/workspace", headers=auth_headers,
            json={"name": original["name"]},
        )
        assert restored.status_code == 200, restored.text
