"""Route governance requires revision fencing, separation and audit."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_governance import (
    RouteConflict, approve_notification_route, draft_notification_route,
)


def db(rowcount=1):
    session = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=rowcount))
    return session


@pytest.mark.asyncio
async def test_new_draft_is_disabled_and_audited():
    session, audit = db(), AsyncMock()
    tenant, actor = uuid4(), uuid4()
    revision = await draft_notification_route(
        session, tenant_id=tenant, channel="email",
        destination_reference="approved:operations", actor_id=actor,
        authorized=True, expected_revision=0, audit=audit,
    )
    assert revision == 1
    record = session.add.call_args.args[0]
    assert record.enabled is False and record.approved is False
    assert record.proposed_by == actor and record.approved_by is None
    session.flush.assert_awaited_once()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_optimistic_update_does_not_keep_approval():
    session, audit = db(), AsyncMock()
    revision = await draft_notification_route(
        session, tenant_id=uuid4(), channel="webhook",
        destination_reference="approved:incident", actor_id=uuid4(),
        authorized=True, expected_revision=2, audit=audit,
    )
    assert revision == 3
    assert "approved" in str(session.execute.await_args.args[0])
    parameters = session.execute.await_args.args[0].compile().params
    assert False in parameters.values()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_revision_cannot_be_drafted_or_approved():
    session, audit = db(rowcount=0), AsyncMock()
    with pytest.raises(RouteConflict):
        await draft_notification_route(
            session, tenant_id=uuid4(), channel="email",
            destination_reference="approved:ops", actor_id=uuid4(),
            authorized=True, expected_revision=3, audit=audit,
        )
    with pytest.raises(RouteConflict):
        await approve_notification_route(
            session, tenant_id=uuid4(), channel="email", revision=2,
            actor_id=uuid4(), authorized=True, audit=audit,
        )
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_approval_is_revision_fenced_and_still_disabled():
    session, audit = db(), AsyncMock()
    actor = uuid4()
    await approve_notification_route(
        session, tenant_id=uuid4(), channel="email",
        revision=2, actor_id=actor, authorized=True, audit=audit,
    )
    params = session.execute.await_args.args[0].compile().params.values()
    assert actor in params
    assert False in params
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_unauthorized_does_not_touch_db_or_audit():
    session, audit = db(), AsyncMock()
    with pytest.raises(PermissionError):
        await approve_notification_route(
            session, tenant_id=uuid4(), channel="email",
            revision=1, actor_id=uuid4(), authorized=False, audit=audit,
        )
    session.execute.assert_not_awaited()
    audit.assert_not_awaited()
