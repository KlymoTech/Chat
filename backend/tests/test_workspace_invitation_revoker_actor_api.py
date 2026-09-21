"""HTTP/database regression for authenticated Workspace invitation revocation provenance."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.security import decode_token


async def test_invitation_revocation_audit_identifies_actual_authenticated_actor(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    async def suppress_real_email(**_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "northstar_api.routers.workspace_invitations.send_workspace_invitation_email",
        suppress_real_email,
    )
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    tenant_id = UUID(workspace.json()["tenantId"])
    workspace_id = UUID(workspace.json()["id"])
    token = auth_headers["Authorization"].split(" ", 1)[1]
    expected_actor = UUID(decode_token(token, "access")["sub"])
    headers = {
        **auth_headers, "X-Workspace-ID": str(workspace_id),
        "User-Agent": "WorkspaceAuditRegression/1.0",
    }

    issued = await client.post("/api/v1/workspace/invitations", headers=headers, json={
        "email": f"revoker-{uuid4().hex}@example.com",
        "role": "viewer", "allAgentsAccess": True, "agentIds": [],
    })
    assert issued.status_code == 201, issued.text
    invitation_id = UUID(issued.json()["id"])
    # An anonymous caller must never be able to revoke or claim an audit actor.
    unauthorized = await client.delete(f"/api/v1/workspace/invitations/{invitation_id}")
    assert unauthorized.status_code == 401, unauthorized.text
    revoked = await client.delete(
        f"/api/v1/workspace/invitations/{invitation_id}", headers=headers,
    )
    assert revoked.status_code == 204, revoked.text

    async with SessionFactory() as session:
        events = list(await session.scalars(select(IntegrationAuditEvent).where(
            IntegrationAuditEvent.tenant_id == tenant_id,
            IntegrationAuditEvent.workspace_id == workspace_id,
            IntegrationAuditEvent.entity_type == "workspace_invitation",
            IntegrationAuditEvent.entity_id == str(invitation_id),
            IntegrationAuditEvent.action == "workspace.invitation.revoked",
        )))
    assert len(events) == 1
    assert events[0].actor_user_id == expected_actor
    assert events[0].category == "access"
    assert events[0].metadata_json == {"role": "viewer", "allAgentsAccess": True}
    assert events[0].user_agent == "WorkspaceAuditRegression/1.0"
    assert events[0].ip_address is not None
