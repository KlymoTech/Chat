"""Fail-closed promotion contract for the persisted platform desired state."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.platform_runtime.contracts import PlatformMetadata, PlatformSpec
from northstar_api.modules.platform_runtime.control_plane import spec_digest
from northstar_api.modules.super_admin.api.runtime import (
    DesiredStateActivationRequest,
    activate_verified_desired_state,
)


def fixtures():
    source = PlatformSpec()
    target = source.model_copy(update={"metadata": PlatformMetadata(revision=2)})
    requester, approver = uuid4(), uuid4()
    change = SimpleNamespace(
        id=uuid4(), status="completed", approved_by=approver, requested_by=requester,
        environment="development", source_revision=1, target_revision=2,
        source_digest=spec_digest(source), target_digest=spec_digest(target),
    )
    current = SimpleNamespace(
        id=uuid4(), environment="development", revision=1,
        configuration_json=source.model_dump(mode="json"), digest=change.source_digest, active=True,
    )
    desired = SimpleNamespace(
        id=uuid4(), environment="development", revision=2,
        configuration_json=target.model_dump(mode="json"), digest=change.target_digest, active=False,
    )
    execution = SimpleNamespace(id=uuid4())
    principal = SimpleNamespace(user_id=uuid4(), tenant_id=uuid4())
    request = DesiredStateActivationRequest(change_id=change.id, reason="verified cutover")
    session = MagicMock()
    session.get = AsyncMock(return_value=change)
    session.scalar = AsyncMock(side_effect=[execution, desired, current])
    session.commit = AsyncMock()
    session.execute = AsyncMock(side_effect=[SimpleNamespace(rowcount=1), SimpleNamespace(rowcount=1)])
    session.rollback = AsyncMock()
    return session, request, principal, change, current, desired


@pytest.mark.asyncio
async def test_successful_promotion_requires_completed_execution(monkeypatch):
    from northstar_api.modules.super_admin.api import runtime

    audit = MagicMock()
    monkeypatch.setattr(runtime, "record_audit_event", audit)
    session, request, principal, _, source, target = fixtures()
    result = await activate_verified_desired_state(request, principal, session)
    assert result["active"] is True
    assert session.execute.await_count == 2
    assert source.active is True and target.active is False  # SQL updates, not in-memory mutation
    session.commit.assert_awaited_once()
    audit.assert_called_once()


@pytest.mark.asyncio
async def test_missing_execution_fails_closed():
    session, request, principal, _, source, target = fixtures()
    session.scalar = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as error:
        await activate_verified_desired_state(request, principal, session)
    assert error.value.status_code == 409
    assert source.active is True and target.active is False
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_current_revision_rejected():
    session, request, principal, _, source, target = fixtures()
    source.revision = 3
    with pytest.raises(HTTPException) as error:
        await activate_verified_desired_state(request, principal, session)
    assert error.value.status_code == 409
    assert target.active is False
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_requestor_cannot_activate():
    session, request, principal, change, _, _ = fixtures()
    principal.user_id = change.requested_by
    with pytest.raises(HTTPException) as error:
        await activate_verified_desired_state(request, principal, session)
    assert error.value.status_code == 403
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_source_retirement_is_rejected():
    session, request, principal, _, _, _ = fixtures()
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))
    with pytest.raises(HTTPException) as error:
        await activate_verified_desired_state(request, principal, session)
    assert error.value.status_code == 409
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_target_update_rolls_back_source_retirement():
    session, request, principal, _, _, _ = fixtures()
    session.execute = AsyncMock(side_effect=[
        SimpleNamespace(rowcount=1), SimpleNamespace(rowcount=0),
    ])
    with pytest.raises(HTTPException) as error:
        await activate_verified_desired_state(request, principal, session)
    assert error.value.status_code == 409
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
