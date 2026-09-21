"""Workspace member details expose only authoritative scoped data."""
from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient


async def test_member_details_are_tenant_scoped_and_accurately_labeled(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    original = await client.get('/api/v1/workspace', headers=auth_headers)
    assert original.status_code == 200, original.text
    original_id = original.json()['id']
    original_headers = {**auth_headers, 'X-Workspace-ID': original_id}
    first = await client.get('/api/v1/workspace/members/details', headers=original_headers)
    assert first.status_code == 200, first.text
    self_member = next(item for item in first.json() if item['userId'] in {
        member['userId'] for member in (await client.get('/api/v1/workspace/members', headers=original_headers)).json()
        if member['isSelf']
    })
    assert isinstance(self_member['mfaEnabled'], bool)
    assert 'lastLoginAt' in self_member  # global account login, not workspace activity
    assert self_member['status'] == 'active'
    assert self_member['invitedByUserId'] is None
    assert self_member['joinedAt']

    other = await client.post('/api/v1/workspaces', headers=auth_headers, json={
        'name': 'Member detail isolation', 'slug': f'member-details-{uuid4().hex[:14]}',
    })
    assert other.status_code == 201, other.text
    other_headers = {**auth_headers, 'X-Workspace-ID': other.json()['id']}
    other_detail = await client.get('/api/v1/workspace/members/details', headers=other_headers)
    assert other_detail.status_code == 200, other_detail.text
    assert {item['userId'] for item in other_detail.json()} == {self_member['userId']}
    assert (await client.get('/api/v1/workspace/members/details', headers={
        **auth_headers, 'X-Workspace-ID': str(uuid4()),
    })).status_code == 403


async def test_accepted_invitation_records_real_inviter_without_token_leak(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch,
) -> None:
    delivered: list[str] = []

    async def capture_invitation(**kwargs) -> None:
        delivered.append(kwargs['raw_token'])

    monkeypatch.setattr('northstar_api.routers.workspace_invitations.send_workspace_invitation_email', capture_invitation)
    workspace = await client.get('/api/v1/workspace', headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, 'X-Workspace-ID': workspace.json()['id']}
    before = await client.get('/api/v1/workspace/members', headers=headers)
    inviter_id = next(item['userId'] for item in before.json() if item['isSelf'])
    email = f'member-details-{uuid4().hex}@example.com'
    issued = await client.post('/api/v1/workspace/invitations', headers=headers, json={
        'email': email, 'role': 'viewer', 'allAgentsAccess': True, 'agentIds': [],
    })
    assert issued.status_code == 201, issued.text
    signup = await client.post('/api/v1/workspace-invitations/signup', json={
        'token': delivered[-1], 'name': 'Details invitee',
        'password': 'Member-Details-Password-42!', 'termsAccepted': True,
        'privacyAccepted': True,
    })
    assert signup.status_code == 201, signup.text
    details = await client.get('/api/v1/workspace/members/details', headers=headers)
    assert details.status_code == 200, details.text
    member = next(item for item in details.json() if item['email'] == email)
    assert member['invitedByUserId'] == inviter_id
    assert member['role'] == 'viewer'
    assert member['status'] == 'active'
    assert 'token' not in str(member).lower()
