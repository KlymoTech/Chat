"""Focused service checks; full HTTP/PostgreSQL/concurrency acceptance is separate."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from northstar_api.modules.workspace.services import owner_recovery
from northstar_api.modules.workspace.services.ownership import (
    WorkspaceOwner, WorkspaceOwnershipError,
)


@pytest.fixture
def setup_recovery(monkeypatch: pytest.MonkeyPatch):
    tenant_id, workspace_id, actor_id, target_id, former_id = (uuid4() for _ in range(5))
    workspace = SimpleNamespace(
        tenant_id=tenant_id, id=workspace_id, created_by=actor_id,
        settings_json={"ownerUserId": str(former_id), "otherSetting": "preserve"},
    )
    lock = AsyncMock(return_value=workspace)
    owner = AsyncMock(return_value=None)
    monkeypatch.setattr(owner_recovery, "locked_workspace", lock)
    monkeypatch.setattr(owner_recovery, "resolve_workspace_owner", owner)
    audit_calls: list[dict] = []
    event_calls: list[dict] = []
    monkeypatch.setattr(owner_recovery, "record_audit_event",
                        lambda _session, **kwargs: audit_calls.append(kwargs))

    def enqueue(_session, **kwargs):
        event_calls.append(kwargs)
        return SimpleNamespace(workspace_id=None)

    monkeypatch.setattr(owner_recovery, "enqueue_event", enqueue)
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=actor_id),
        execute=AsyncMock(return_value=SimpleNamespace(first=lambda: (target_id, "Next administrator"))),
        flush=AsyncMock(),
    )
    inputs = dict(
        tenant_id=tenant_id, workspace_id=workspace_id,
        actor_user_id=actor_id, target_user_id=target_id,
        reason="recorded_owner_unavailable",
    )
    return SimpleNamespace(
        session=session, inputs=inputs, workspace=workspace, lock=lock,
        owner=owner, audit_calls=audit_calls, event_calls=event_calls,
        target_id=target_id, actor_id=actor_id, former_id=former_id,
    )


async def test_recovery_stages_exactly_one_scoped_allowlisted_event_without_committing(setup_recovery) -> None:
    ctx = setup_recovery
    result = await owner_recovery.recover_workspace_ownership(ctx.session, **ctx.inputs)
    assert result.owner.user_id == ctx.target_id
    assert result.owner.name == "Next administrator"
    assert result.creator_user_id == ctx.actor_id
    assert ctx.workspace.settings_json == {
        "ownerUserId": str(ctx.target_id), "otherSetting": "preserve",
    }
    assert len(ctx.audit_calls) == len(ctx.event_calls) == 1
    audit, event = ctx.audit_calls[0], ctx.event_calls[0]
    assert audit["tenant_id"] == event["tenant_id"] == ctx.inputs["tenant_id"]
    assert audit["workspace_id"] == ctx.inputs["workspace_id"]
    assert audit["actor_user_id"] == ctx.actor_id
    assert audit["action"] == "workspace.owner.recovered"
    assert event["event_type"] == "workspace.owner.recovered.v1"
    assert event["payload"]["workspaceId"] == str(ctx.inputs["workspace_id"])
    assert event["payload"]["reasonCode"] == "recorded_owner_unavailable"
    assert str(ctx.former_id) not in str(event["payload"])
    ctx.session.flush.assert_awaited_once()
    ctx.lock.assert_awaited_once()


async def test_recovery_cannot_self_appoint(setup_recovery) -> None:
    ctx = setup_recovery
    with pytest.raises(WorkspaceOwnershipError) as caught:
        await owner_recovery.recover_workspace_ownership(
            ctx.session, **(ctx.inputs | {"target_user_id": ctx.actor_id}),
        )
    assert caught.value.status_code == 409
    ctx.lock.assert_not_awaited()
    assert not ctx.audit_calls and not ctx.event_calls


async def test_recovery_requires_database_verified_tenant_owner(setup_recovery) -> None:
    ctx = setup_recovery
    ctx.session.scalar.return_value = None
    with pytest.raises(WorkspaceOwnershipError) as caught:
        await owner_recovery.recover_workspace_ownership(ctx.session, **ctx.inputs)
    assert caught.value.status_code == 403
    ctx.session.execute.assert_not_awaited()
    assert not ctx.audit_calls and not ctx.event_calls


async def test_recovery_rejects_active_owner_and_wrong_reason(setup_recovery) -> None:
    ctx = setup_recovery
    ctx.owner.return_value = WorkspaceOwner(ctx.actor_id, "Active owner")
    with pytest.raises(WorkspaceOwnershipError) as caught:
        await owner_recovery.recover_workspace_ownership(ctx.session, **ctx.inputs)
    assert caught.value.status_code == 409
    ctx.owner.return_value = None
    with pytest.raises(WorkspaceOwnershipError) as caught:
        await owner_recovery.recover_workspace_ownership(
            ctx.session, **(ctx.inputs | {"reason": "legacy_owner_unavailable"}),
        )
    assert caught.value.status_code == 422
    ctx.session.execute.assert_not_awaited()
    assert not ctx.audit_calls and not ctx.event_calls


async def test_recovery_rejects_ineligible_target(setup_recovery) -> None:
    ctx = setup_recovery
    ctx.session.execute.return_value = SimpleNamespace(first=lambda: None)
    with pytest.raises(WorkspaceOwnershipError) as caught:
        await owner_recovery.recover_workspace_ownership(ctx.session, **ctx.inputs)
    assert caught.value.status_code == 409
    ctx.session.flush.assert_not_awaited()
    assert not ctx.audit_calls and not ctx.event_calls
