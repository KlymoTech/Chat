"""Recovery cannot silently reassign ownership or let a Workspace admin bypass tenant authority."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.models import (
    OutboxEvent, Role, TenantMembership, User, Workspace, WorkspaceMembership, WorkspaceRole,
)


async def test_recovery_requires_unavailable_owner_distinct_active_admin_and_tenant_owner(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    created = await client.post('/api/v1/workspaces', headers=auth_headers, json={
        'name': 'Recovery isolation', 'slug': f'owner-recover-{uuid4().hex[:14]}',
    })
    assert created.status_code == 201, created.text
    tenant_id, workspace_id = UUID(created.json()['tenantId']), UUID(created.json()['id'])
    headers = {**auth_headers, 'X-Workspace-ID': str(workspace_id)}
    owner_response = await client.get('/api/v1/workspace/owner', headers=headers)
    assert owner_response.status_code == 200, owner_response.text
    actor_id = UUID(owner_response.json()['ownerUserId'])
    target_id = uuid4()
    bad_owner_id = uuid4()
    async with SessionFactory() as session:
        session.add(User(id=target_id, email=f'owner-recovery-{uuid4().hex}@example.com',
                         name='Recovery candidate', password_hash='test-only-login-disabled', is_active=True))
        session.add(TenantMembership(tenant_id=tenant_id, user_id=target_id, role=Role.MEMBER))
        session.add(WorkspaceMembership(tenant_id=tenant_id, workspace_id=workspace_id,
                                        user_id=target_id, role=WorkspaceRole.ADMIN, all_agents_access=True))
        await session.commit()

    payload = {'targetUserId': str(target_id), 'confirmation': 'RECOVER', 'reason': 'recorded_owner_unavailable'}
    try:
        still_owned = await client.post('/api/v1/workspace/owner/recover', headers=headers, json=payload)
        assert still_owned.status_code == 409, still_owned.text
        async with SessionFactory() as session:
            workspace = await session.get(Workspace, workspace_id)
            assert workspace is not None
            workspace.settings_json = {**(workspace.settings_json or {}), 'ownerUserId': str(bad_owner_id)}
            await session.commit()

        self_recovery = await client.post('/api/v1/workspace/owner/recover', headers=headers,
                                          json={**payload, 'targetUserId': str(actor_id)})
        assert self_recovery.status_code == 409, self_recovery.text
        invalid_confirmation = await client.post('/api/v1/workspace/owner/recover', headers=headers,
                                                  json={**payload, 'confirmation': 'TRANSFER'})
        assert invalid_confirmation.status_code == 422, invalid_confirmation.text
        wrong_reason = await client.post('/api/v1/workspace/owner/recover', headers=headers,
                                         json={**payload, 'reason': 'legacy_owner_unavailable'})
        assert wrong_reason.status_code == 422, wrong_reason.text
        wrong_workspace = await client.post('/api/v1/workspace/owner/recover', headers={
            **auth_headers, 'X-Workspace-ID': str(uuid4()),
        }, json=payload)
        assert wrong_workspace.status_code == 403, wrong_workspace.text

        result = await client.post('/api/v1/workspace/owner/recover', headers=headers, json=payload)
        assert result.status_code == 200, result.text
        assert result.json()['ownerUserId'] == str(target_id)
        retry = await client.post('/api/v1/workspace/owner/recover', headers=headers, json=payload)
        assert retry.status_code == 409, retry.text

        async with SessionFactory() as session:
            workspace = await session.get(Workspace, workspace_id)
            assert workspace is not None
            assert workspace.settings_json['ownerUserId'] == str(target_id)
            audits = list(await session.scalars(select(IntegrationAuditEvent).where(
                IntegrationAuditEvent.tenant_id == tenant_id,
                IntegrationAuditEvent.workspace_id == workspace_id,
                IntegrationAuditEvent.action == 'workspace.owner.recovered',
            )))
            events = list(await session.scalars(select(OutboxEvent).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.workspace_id == workspace_id,
                OutboxEvent.event_type == 'workspace.owner.recovered.v1',
            )))
            assert len(audits) == len(events) == 1
            assert audits[0].actor_user_id == actor_id
            assert audits[0].metadata_json['reasonCode'] == 'recorded_owner_unavailable'
            assert events[0].payload['recoveredOwnerUserId'] == str(target_id)
            assert str(bad_owner_id) not in str(events[0].payload)
    finally:
        async with SessionFactory() as session:
            workspace = await session.get(Workspace, workspace_id)
            if workspace is not None:
                workspace.settings_json = {
                    key: value for key, value in (workspace.settings_json or {}).items()
                    if key != 'ownerUserId'
                }
            member = await session.get(WorkspaceMembership, (workspace_id, target_id))
            if member is not None:
                await session.delete(member)
            tenant_member = await session.get(TenantMembership, (tenant_id, target_id))
            if tenant_member is not None:
                await session.delete(tenant_member)
            user = await session.get(User, target_id)
            if user is not None:
                await session.delete(user)
            await session.commit()
