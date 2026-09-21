"""Invitation events contain scoped allowlisted data, never invitation credentials."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from northstar_api.modules.workspace.models.member_invitation_origin import WorkspaceMemberInvitationOrigin
from northstar_api.modules.workspace.services import invitation_audit


@pytest.mark.parametrize('action', [
    'invited', 'resent', 'revoked', 'accepted', 'declined',
    'delivery_succeeded', 'delivery_failed',
])
def test_invitation_transition_stages_scoped_secret_free_audit_and_outbox(
    monkeypatch: pytest.MonkeyPatch, action: invitation_audit.InvitationAction,
) -> None:
    audit_calls: list[dict[str, object]] = []
    event_calls: list[dict[str, object]] = []
    origins: list[WorkspaceMemberInvitationOrigin] = []
    event = SimpleNamespace(workspace_id=None)
    monkeypatch.setattr(invitation_audit, 'record_audit_event',
                        lambda _session, **kwargs: audit_calls.append(kwargs))
    monkeypatch.setattr(invitation_audit, 'enqueue_event',
                        lambda _session, **kwargs: (event_calls.append(kwargs), event)[1])
    tenant_id, workspace_id, invitation_id, actor_id = (uuid4() for _ in range(4))
    session = SimpleNamespace(add=lambda origin: origins.append(origin))
    invitation_audit.stage_invitation_transition(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
        invitation_id=invitation_id, actor_user_id=actor_id,
        action=action, role='viewer', all_agents_access=False, agent_count=2,
    )
    assert len(audit_calls) == len(event_calls) == 1
    audit, outbox = audit_calls[0], event_calls[0]
    assert audit['tenant_id'] == outbox['tenant_id'] == tenant_id
    assert audit['workspace_id'] == event.workspace_id == workspace_id
    assert audit['actor_user_id'] == actor_id
    assert audit['entity_id'] == str(invitation_id)
    assert outbox['aggregate_id'] == invitation_id
    assert audit['action'] == f'workspace.invitation.{action}'
    assert outbox['event_type'] == f'workspace.invitation.{action}.v1'
    assert outbox['payload'] == {
        'workspaceId': str(workspace_id), 'invitationId': str(invitation_id),
        'role': 'viewer', 'allAgentsAccess': False, 'agentCount': 2,
    }
    assert len(origins) == (1 if action == 'accepted' else 0)
    if origins:
        origin = origins[0]
        assert origin.tenant_id == tenant_id
        assert origin.workspace_id == workspace_id
        assert origin.user_id == actor_id
        assert origin.invitation_id == invitation_id
    for data in (audit, outbox):
        contents = str(data).lower()
        assert 'token' not in contents
        assert 'password' not in contents
        assert 'recipient' not in contents
        assert 'secret' not in contents


def test_invitation_audit_does_not_invent_an_actor_for_public_decline(monkeypatch: pytest.MonkeyPatch) -> None:
    audited: list[dict[str, object]] = []
    monkeypatch.setattr(invitation_audit, 'record_audit_event',
                        lambda _session, **kwargs: audited.append(kwargs))
    monkeypatch.setattr(invitation_audit, 'enqueue_event',
                        lambda _session, **_kwargs: SimpleNamespace(workspace_id=None))
    invitation_audit.stage_invitation_transition(
        object(), tenant_id=uuid4(), workspace_id=uuid4(), invitation_id=uuid4(),
        actor_user_id=None, action='declined', role='operator', all_agents_access=True,
    )
    assert audited[0]['actor_user_id'] is None


def test_accepted_invitation_without_invitee_identity_fails_closed() -> None:
    with pytest.raises(ValueError, match='accepted member identity'):
        invitation_audit.stage_invitation_transition(
            object(), tenant_id=uuid4(), workspace_id=uuid4(), invitation_id=uuid4(),
            actor_user_id=None, action='accepted', role='viewer', all_agents_access=True,
        )
