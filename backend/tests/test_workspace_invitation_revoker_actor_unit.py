"""Regression: invitation revocation identifies its actual authenticated administrator."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from northstar_api.modules.workspace.services import invitation_actor, invitation_audit


def _stage(session: SimpleNamespace, tenant_id, workspace_id, action: invitation_audit.InvitationAction) -> None:
    invitation_audit.stage_invitation_transition(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
        invitation_id=uuid4(), actor_user_id=None, action=action,
        role="operator", all_agents_access=False,
    )


def test_authenticated_revoker_is_recorded_only_for_matching_tenant_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    audits: list[dict[str, object]] = []
    monkeypatch.setattr(invitation_audit, "record_audit_event", lambda _session, **kwargs: audits.append(kwargs))
    monkeypatch.setattr(invitation_audit, "enqueue_event", lambda _session, **kwargs: SimpleNamespace(workspace_id=None))
    tenant_id, workspace_id, another_tenant, another_workspace, actor_id = (uuid4() for _ in range(5))
    session = SimpleNamespace(info={})
    principal = SimpleNamespace(tenant_id=tenant_id, workspace_id=workspace_id, user_id=actor_id)
    asyncio.run(invitation_actor.capture_invitation_administrator(principal, session))

    _stage(session, tenant_id, workspace_id, "revoked")
    _stage(session, another_tenant, workspace_id, "revoked")
    _stage(session, tenant_id, another_workspace, "revoked")
    _stage(session, tenant_id, workspace_id, "declined")
    assert [item["actor_user_id"] for item in audits] == [actor_id, None, None, None]
    assert all("email" not in str(item).lower() and "token" not in str(item).lower() for item in audits)


def test_org_only_context_clears_any_previous_actor() -> None:
    tenant_id, workspace_id, actor_id = (uuid4() for _ in range(3))
    session = SimpleNamespace(info={})
    asyncio.run(invitation_actor.capture_invitation_administrator(
        SimpleNamespace(tenant_id=tenant_id, workspace_id=workspace_id, user_id=actor_id), session,
    ))
    asyncio.run(invitation_actor.capture_invitation_administrator(
        SimpleNamespace(tenant_id=tenant_id, workspace_id=None, user_id=actor_id), session,
    ))
    assert invitation_actor.invitation_revoker_actor(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
    ) is None


def test_non_uuid_actor_is_not_trusted() -> None:
    tenant_id, workspace_id = uuid4(), uuid4()
    session = SimpleNamespace(info={
        "workspace_invitation_authenticated_scope": (tenant_id, workspace_id),
        "workspace_invitation_authenticated_actor": "client-controlled-string",
    })
    assert invitation_actor.invitation_revoker_actor(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
    ) is None
