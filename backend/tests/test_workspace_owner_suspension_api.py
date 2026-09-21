"""A suspended Workspace administrator cannot become the owner."""
from __future__ import annotations

from uuid import UUID, uuid4

from httpx import AsyncClient

from northstar_api.database import SessionFactory
from northstar_api.models import Role, TenantMembership, User, Workspace, WorkspaceMembership, WorkspaceRole
from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState


async def test_owner_transfer_rejects_suspended_admin_and_allows_reactivated_admin(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    created = await client.post('/api/v1/workspaces', headers=auth_headers, json={
        'name': 'Owner suspension regression', 'slug': f'owner-suspension-{uuid4().hex[:14]}',
    })
    assert created.status_code == 201, created.text
    tenant_id, workspace_id = UUID(created.json()['tenantId']), UUID(created.json()['id'])
    headers = {**auth_headers, 'X-Workspace-ID': str(workspace_id)}
    owner = await client.get('/api/v1/workspace/owner', headers=headers)
    assert owner.status_code == 200, owner.text
    initial_owner = owner.json()['ownerUserId']
    assert initial_owner

    target_id = uuid4()
    async with SessionFactory() as session:
        session.add(User(
            id=target_id, email=f'owner-suspension-{uuid4().hex}@example.com',
            name='Suspension target', password_hash='test-only-login-disabled', is_active=True,
        ))
        session.add(TenantMembership(tenant_id=tenant_id, user_id=target_id, role=Role.MEMBER))
        session.add(WorkspaceMembership(
            tenant_id=tenant_id, workspace_id=workspace_id, user_id=target_id,
            role=WorkspaceRole.ADMIN, all_agents_access=True,
        ))
        await session.commit()

    transfer = {
        'expectedOwnerUserId': initial_owner,
        'targetUserId': str(target_id),
        'confirmation': 'TRANSFER', 'reason': 'administrative_handover',
    }
    try:
        suspended = await client.post(
            f'/api/v1/workspace/members/{target_id}/suspend', headers=headers,
            json={'reason': 'Administrative security review', 'confirmation': 'SUSPEND'},
        )
        assert suspended.status_code == 200, suspended.text
        denied = await client.post('/api/v1/workspace/owner/transfer', headers=headers, json=transfer)
        assert denied.status_code == 409, denied.text
        unchanged = await client.get('/api/v1/workspace/owner', headers=headers)
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()['ownerUserId'] == initial_owner

        reactivated = await client.post(
            f'/api/v1/workspace/members/{target_id}/reactivate', headers=headers,
            json={'reason': 'Security review completed', 'confirmation': 'REACTIVATE'},
        )
        assert reactivated.status_code == 200, reactivated.text
        transferred = await client.post('/api/v1/workspace/owner/transfer', headers=headers, json=transfer)
        assert transferred.status_code == 200, transferred.text
        assert transferred.json()['ownerUserId'] == str(target_id)
    finally:
        async with SessionFactory() as session:
            workspace = await session.get(Workspace, workspace_id)
            if workspace is not None:
                workspace.settings_json = {
                    key: value for key, value in (workspace.settings_json or {}).items()
                    if key != 'ownerUserId'
                }
            state = await session.get(WorkspaceMemberState, (workspace_id, target_id))
            if state is not None:
                await session.delete(state)
            membership = await session.get(WorkspaceMembership, (workspace_id, target_id))
            if membership is not None:
                await session.delete(membership)
            tenant_member = await session.get(TenantMembership, (tenant_id, target_id))
            if tenant_member is not None:
                await session.delete(tenant_member)
            user = await session.get(User, target_id)
            if user is not None:
                await session.delete(user)
            await session.commit()
