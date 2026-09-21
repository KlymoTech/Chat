"""HTTP/database regressions for workspace owner handover and member safety."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import (
    OutboxEvent, Role, TenantMembership, User, Workspace,
    WorkspaceMembership, WorkspaceRole,
)


async def test_workspace_owner_transfer_is_confirmed_scoped_and_audited(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    current = await client.get("/api/v1/workspace", headers=auth_headers)
    assert current.status_code == 200, current.text
    workspace_id = UUID(current.json()["id"])
    tenant_id = UUID(current.json()["tenantId"])
    initial = await client.get("/api/v1/workspace/owner", headers=auth_headers)
    assert initial.status_code == 200, initial.text
    initial_owner_id = UUID(initial.json()["ownerUserId"])
    assert initial.json()["creatorUserId"] is not None

    invitee_id = uuid4()
    async with SessionFactory() as session:
        workspace = await session.get(Workspace, workspace_id)
        assert workspace is not None
        original_settings = dict(workspace.settings_json or {})
        session.add(User(
            id=invitee_id, name="Owner handover fixture",
            email=f"ownership-{uuid4().hex}@example.com",
            password_hash="test-only-login-disabled", is_active=True,
        ))
        session.add(TenantMembership(
            tenant_id=tenant_id, user_id=invitee_id, role=Role.MEMBER,
        ))
        session.add(WorkspaceMembership(
            workspace_id=workspace_id, tenant_id=tenant_id,
            user_id=invitee_id, role=WorkspaceRole.ADMIN, all_agents_access=True,
        ))
        await session.commit()

    async def entries() -> tuple[set[UUID], set[UUID]]:
        async with SessionFactory() as session:
            audits = set(await session.scalars(select(IntegrationAuditEvent.id).where(
                IntegrationAuditEvent.tenant_id == tenant_id,
                IntegrationAuditEvent.workspace_id == workspace_id,
                IntegrationAuditEvent.action == "workspace.owner.transferred",
            )))
            outbox = set(await session.scalars(select(OutboxEvent.id).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.event_type == "workspace.owner.transferred.v1",
            )))
            return audits, outbox

    before = await entries()
    try:
        base = {
            "expectedOwnerUserId": str(initial_owner_id),
            "targetUserId": str(invitee_id),
            "reason": "administrative_handover",
        }
        missing_confirmation = await client.post(
            "/api/v1/workspace/owner/transfer", headers=auth_headers, json=base,
        )
        assert missing_confirmation.status_code == 422, missing_confirmation.text
        assert await entries() == before
        transferred = await client.post(
            "/api/v1/workspace/owner/transfer", headers=auth_headers,
            json={**base, "confirmation": "TRANSFER"},
        )
        assert transferred.status_code == 200, transferred.text
        assert transferred.json()["ownerUserId"] == str(invitee_id)
        assert transferred.json()["creatorUserId"] == initial.json()["creatorUserId"]
        reread = await client.get("/api/v1/workspace/owner", headers=auth_headers)
        assert reread.status_code == 200, reread.text
        assert reread.json()["ownerUserId"] == str(invitee_id)

        stale = await client.post(
            "/api/v1/workspace/owner/transfer", headers=auth_headers,
            json={**base, "targetUserId": str(initial_owner_id), "confirmation": "TRANSFER"},
        )
        assert stale.status_code == 409, stale.text
        protected = await client.delete(
            f"/api/v1/workspace/members/{invitee_id}", headers=auth_headers,
        )
        assert protected.status_code == 409, protected.text
        assert "transfer workspace ownership" in protected.text.lower()

        audits, events = await entries()
        assert len(audits - before[0]) == 1
        assert len(events - before[1]) == 1
        async with SessionFactory() as session:
            event = await session.get(OutboxEvent, next(iter(events - before[1])))
            assert event is not None
            assert event.workspace_id == workspace_id
            assert event.payload["newOwnerUserId"] == str(invitee_id)
            assert "password" not in str(event.payload).lower()
    finally:
        async with SessionFactory() as session:
            workspace = await session.get(Workspace, workspace_id)
            assert workspace is not None
            workspace.settings_json = original_settings
            membership = await session.get(WorkspaceMembership, (workspace_id, invitee_id))
            if membership is not None:
                await session.delete(membership)
            tenant_member = await session.get(TenantMembership, (tenant_id, invitee_id))
            if tenant_member is not None:
                await session.delete(tenant_member)
            user = await session.get(User, invitee_id)
            if user is not None:
                await session.delete(user)
            await session.commit()
