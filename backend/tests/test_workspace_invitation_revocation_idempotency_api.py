"""Regression for idempotent Workspace invitation revocation with real HTTP and DB."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory, set_tenant_context
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.workspace_invitations import WorkspaceInvitation


async def test_repeat_revoke_does_not_rotate_token_or_duplicate_audit(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    async def suppress_email(**_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        suppress_email,
    )
    workspace_response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace_response.status_code == 200, workspace_response.text
    tenant_id = UUID(workspace_response.json()["tenantId"])
    workspace_id = UUID(workspace_response.json()["id"])
    headers = {**auth_headers, "X-Workspace-ID": str(workspace_id)}
    created = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": f"idempotent-revoke-{uuid4().hex}@example.com",
        "role": "viewer", "allAgentsAccess": True, "agentIds": [],
    })
    assert created.status_code == 201, created.text
    invitation_id = UUID(created.json()["id"])
    url = f"/api/v1/workspace/invitations/{invitation_id}"
    first = await client.delete(url, headers=headers)
    assert first.status_code == 204, first.text

    async def state() -> tuple[str, object, object, int]:
        async with SessionFactory() as session:
            await set_tenant_context(session, tenant_id)
            row = await session.scalar(select(WorkspaceInvitation).where(
                WorkspaceInvitation.id == invitation_id,
                WorkspaceInvitation.tenant_id == tenant_id,
                WorkspaceInvitation.workspace_id == workspace_id,
            ))
            assert row is not None
            count = await session.scalar(select(func.count()).select_from(IntegrationAuditEvent).where(
                IntegrationAuditEvent.tenant_id == tenant_id,
                IntegrationAuditEvent.workspace_id == workspace_id,
                IntegrationAuditEvent.entity_type == "workspace_invitation",
                IntegrationAuditEvent.entity_id == str(invitation_id),
                IntegrationAuditEvent.action == "workspace.invitation.revoked",
            ))
            return row.token_hash, row.revoked_at, row.updated_at, int(count or 0)

    original = await state()
    assert original[3] == 1
    second = await client.delete(url, headers=headers)
    assert second.status_code == 204, second.text
    third = await client.delete(url, headers=headers)
    assert third.status_code == 204, third.text
    assert await state() == original
