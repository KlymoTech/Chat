"""HTTP/database checks for invitation audit/outbox lifecycle and token safety."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import OutboxEvent


async def _history(tenant_id: UUID, workspace_id: UUID, invitation_id: UUID):
    async with SessionFactory() as session:
        audits = list(await session.scalars(select(IntegrationAuditEvent).where(
            IntegrationAuditEvent.tenant_id == tenant_id,
            IntegrationAuditEvent.workspace_id == workspace_id,
            IntegrationAuditEvent.entity_type == 'workspace_invitation',
            IntegrationAuditEvent.entity_id == str(invitation_id),
        )))
        events = list(await session.scalars(select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.workspace_id == workspace_id,
            OutboxEvent.aggregate_type == 'workspace_invitation',
            OutboxEvent.aggregate_id == str(invitation_id),
        )))
        return audits, events


async def test_invitation_issue_resend_decline_reissue_accept_are_scoped_and_secret_free(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    delivered_tokens: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        delivered_tokens.append(kwargs['raw_token'])

    monkeypatch.setattr('northstar_api.routers.workspace_invitations.send_workspace_invitation_email', capture_invitation)
    current = await client.get('/api/v1/workspace', headers=auth_headers)
    assert current.status_code == 200, current.text
    tenant_id, workspace_id = UUID(current.json()['tenantId']), UUID(current.json()['id'])
    headers = {**auth_headers, 'X-Workspace-ID': str(workspace_id)}
    email = f'audit-invite-{uuid4().hex}@example.com'
    payload = {'email': email, 'role': 'operator', 'allAgentsAccess': True, 'agentIds': []}
    issued = await client.post('/api/v1/workspace/invitations', headers=headers, json=payload)
    assert issued.status_code == 201, issued.text
    invitation_id = UUID(issued.json()['id'])
    assert delivered_tokens
    first_token = delivered_tokens[-1]
    resent = await client.post(
        f'/api/v1/workspace/invitations/{invitation_id}/resend', headers=headers,
    )
    assert resent.status_code == 200, resent.text
    second_token = delivered_tokens[-1]
    assert first_token != second_token
    decline = await client.post('/api/v1/workspace-invitations/decline', json={'token': second_token})
    assert decline.status_code == 200, decline.text

    reissued = await client.post('/api/v1/workspace/invitations', headers=headers, json=payload)
    assert reissued.status_code == 201, reissued.text
    assert reissued.json()['id'] == str(invitation_id)
    signup = await client.post('/api/v1/workspace-invitations/signup', json={
        'token': delivered_tokens[-1], 'name': 'Invitation audit member',
        'password': 'Invitation-Audit-Password-42!',
        'termsAccepted': True, 'privacyAccepted': True,
    })
    assert signup.status_code == 201, signup.text

    audits, events = await _history(tenant_id, workspace_id, invitation_id)
    expected = {
        'workspace.invitation.invited', 'workspace.invitation.resent',
        'workspace.invitation.delivery_succeeded', 'workspace.invitation.declined',
        'workspace.invitation.accepted',
    }
    assert expected <= {row.action for row in audits}
    assert {f'{action}.v1' for action in expected} <= {row.event_type for row in events}
    assert sum(row.action == 'workspace.invitation.invited' for row in audits) == 2
    assert sum(row.action == 'workspace.invitation.delivery_succeeded' for row in audits) == 3
    assert len(audits) == len(events) == 8
    for row in events:
        assert row.tenant_id == tenant_id and row.workspace_id == workspace_id
        assert row.payload['workspaceId'] == str(workspace_id)
        assert row.payload['invitationId'] == str(invitation_id)
        contents = str(row.payload)
        assert first_token not in contents and second_token not in contents
        assert email not in contents
        assert 'token' not in contents.lower()
    for row in audits:
        assert first_token not in str(row.metadata_json)
        assert email not in str(row.metadata_json)

    other = await client.get('/api/v1/workspace/members/details', headers={
        **auth_headers, 'X-Workspace-ID': str(uuid4()),
    })
    assert other.status_code == 403, other.text


async def test_revocation_stages_audit_and_event_without_exposing_the_token(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    tokens: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        tokens.append(kwargs['raw_token'])

    monkeypatch.setattr('northstar_api.routers.workspace_invitations.send_workspace_invitation_email', capture_invitation)
    workspace = await client.get('/api/v1/workspace', headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    tenant_id, workspace_id = UUID(workspace.json()['tenantId']), UUID(workspace.json()['id'])
    headers = {**auth_headers, 'X-Workspace-ID': str(workspace_id)}
    issued = await client.post('/api/v1/workspace/invitations', headers=headers, json={
        'email': f'revoke-audit-{uuid4().hex}@example.com',
        'role': 'viewer', 'allAgentsAccess': True, 'agentIds': [],
    })
    assert issued.status_code == 201, issued.text
    invitation_id = UUID(issued.json()['id'])
    revoked = await client.delete(f'/api/v1/workspace/invitations/{invitation_id}', headers=headers)
    assert revoked.status_code == 204, revoked.text
    audits, events = await _history(tenant_id, workspace_id, invitation_id)
    assert 'workspace.invitation.revoked' in {row.action for row in audits}
    assert 'workspace.invitation.revoked.v1' in {row.event_type for row in events}
    assert all(tokens[-1] not in str(row.payload) for row in events)
