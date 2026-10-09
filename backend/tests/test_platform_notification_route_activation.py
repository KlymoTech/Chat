"""Route activation requires approval, preflight, revision fencing and audit."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_activation import activate_notification_route
from northstar_api.modules.platform_runtime.queue_notification_config import ApprovedNotificationRoute
from northstar_api.modules.platform_runtime.queue_notification_governance import RouteConflict


def route(approved=True, enabled=False):
    return ApprovedNotificationRoute(uuid4(), "webhook", "approved:incident", 4, enabled, approved)


@pytest.mark.asyncio
async def test_approved_preflight_allows_audited_activation():
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    audit, preflight = AsyncMock(), AsyncMock(return_value=True)
    item = route()
    revision = await activate_notification_route(
        db, route=item, expected_revision=4, actor_id=uuid4(),
        authorized=True, preflight=preflight, audit=audit,
    )
    assert revision == 5
    preflight.assert_awaited_once_with(item)
    statement = db.execute.await_args.args[0]
    assert item.tenant_id in statement.compile().params.values()
    assert item.destination_reference in statement.compile().params.values()
    assert True in statement.compile().params.values()
    audit.assert_awaited_once()
    assert audit.await_args.args[1]["action"] == "platform.notification_route.activated"


@pytest.mark.asyncio
@pytest.mark.parametrize("approved,enabled", [(False, False), (True, True)])
async def test_unapproved_or_active_route_never_preflights(approved, enabled):
    db, preflight = MagicMock(), AsyncMock()
    with pytest.raises(RouteConflict):
        await activate_notification_route(
            db, route=route(approved, enabled), expected_revision=4,
            actor_id=uuid4(), authorized=True, preflight=preflight,
            audit=AsyncMock(),
        )
    preflight.assert_not_awaited()
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_preflight_error_blocks_database_mutation():
    db, audit = MagicMock(), AsyncMock()
    with pytest.raises(RouteConflict, match="preflight"):
        await activate_notification_route(
            db, route=route(), expected_revision=4, actor_id=uuid4(),
            authorized=True, preflight=AsyncMock(side_effect=RuntimeError("secret")),
            audit=audit,
        )
    db.execute.assert_not_called()
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_revision_change_blocks_audit():
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    audit = AsyncMock()
    with pytest.raises(RouteConflict, match="changed"):
        await activate_notification_route(
            db, route=route(), expected_revision=4, actor_id=uuid4(),
            authorized=True, preflight=AsyncMock(return_value=True), audit=audit,
        )
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_authorization_blocks_preflight():
    db, preflight = MagicMock(), AsyncMock()
    with pytest.raises(PermissionError):
        await activate_notification_route(
            db, route=route(), expected_revision=4, actor_id=uuid4(),
            authorized=False, preflight=preflight, audit=AsyncMock(),
        )
    preflight.assert_not_awaited()
    db.execute.assert_not_called()
