"""HTTP/database regression: invalid explicit ownership requires recovery, not fallback."""
from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import OutboxEvent, Workspace


async def test_explicit_invalid_owner_fails_closed_without_reassigning_or_emitting_events(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    tenant_id = current.json()["tenantId"]
    original_owner = await client.get("/api/v1/workspace/owner", headers=auth_headers)
    assert original_owner.status_code == 200, original_owner.text
    assert original_owner.json()["ownerUserId"] is not None

    # Create a distinct workspace rather than mutate the shared fixture.
    created = await client.post(
        "/api/v1/workspaces", headers=auth_headers,
        json={"name": "Fail-closed owner regression", "slug": f"owner-recovery-{uuid4().hex[:16]}"},
    )
    assert created.status_code == 201, created.text
    selected_id = created.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": selected_id}
    absent_id = str(uuid4())
    async with SessionFactory() as session:
        workspace = await session.scalar(select(Workspace).where(
            Workspace.id == selected_id, Workspace.tenant_id == tenant_id,
        ))
        assert workspace is not None
        original_creator = str(workspace.created_by)
        workspace.settings_json = {**(workspace.settings_json or {}), "ownerUserId": absent_id}
        await session.commit()

    owner = await client.get("/api/v1/workspace/owner", headers=headers)
    assert owner.status_code == 200, owner.text
    assert owner.json()["ownerUserId"] is None
    assert owner.json()["creatorUserId"] == original_creator

    denied = await client.post(
        "/api/v1/workspace/owner/transfer", headers=headers,
        json={
            "expectedOwnerUserId": original_creator,
            "targetUserId": str(uuid4()),
            "reason": "account_recovery", "confirmation": "TRANSFER",
        },
    )
    assert denied.status_code == 409, denied.text
    assert "recover access" in denied.text.lower()
    after = await client.get("/api/v1/workspace/owner", headers=headers)
    assert after.status_code == 200 and after.json()["ownerUserId"] is None
    async with SessionFactory() as session:
        workspace = await session.scalar(select(Workspace).where(Workspace.id == selected_id))
        assert workspace is not None
        assert workspace.settings_json["ownerUserId"] == absent_id
        audits = list(await session.scalars(select(IntegrationAuditEvent).where(
            IntegrationAuditEvent.tenant_id == tenant_id,
            IntegrationAuditEvent.workspace_id == workspace.id,
            IntegrationAuditEvent.action == "workspace.owner.transferred",
        )))
        events = list(await session.scalars(select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.workspace_id == workspace.id,
            OutboxEvent.event_type == "workspace.owner.transferred.v1",
        )))
        assert not audits and not events
