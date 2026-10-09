"""Admin route readback and deactivation security contracts."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.platform_runtime.queue_notification_governance import (
    RouteConflict, deactivate_notification_route,
)
from northstar_api.modules.super_admin.api import runtime
from northstar_api.modules.super_admin.api.runtime import (
    NotificationRouteDeactivateRequest,
    deactivate_platform_notification_route,
    read_platform_notification_route,
)


@pytest.mark.asyncio
async def test_readback_scopes_tenant_and_omits_destination():
    tenant = uuid4()
    principal = SimpleNamespace(tenant_id=tenant)
    record = SimpleNamespace(
        channel="email", revision=3, enabled=False, approved=True,
        destination_reference="approved:private-secret",
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=record)
    output = await read_platform_notification_route("email", principal, session)
    assert output == {"channel": "email", "revision": 3, "enabled": False,
                      "approved": True, "configured": True}
    statement = session.scalar.await_args.args[0]
    assert tenant in statement.compile().params.values()
    assert "private-secret" not in str(output)


@pytest.mark.asyncio
async def test_readback_fails_closed_for_missing_tenant():
    session = MagicMock()
    session.scalar = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await read_platform_notification_route(
            "email", SimpleNamespace(tenant_id=None), session,
        )
    assert error.value.status_code == 403
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_revision_fenced_service_audits_and_disables():
    session = MagicMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
    audit = AsyncMock()
    tenant, actor = uuid4(), uuid4()
    revision = await deactivate_notification_route(
        session, tenant_id=tenant, channel="webhook", expected_revision=4,
        actor_id=actor, authorized=True, audit=audit,
    )
    assert revision == 5
    params = session.execute.await_args.args[0].compile().params
    assert tenant in params.values()
    assert 4 in params.values() and 5 in params.values()
    assert False in params.values()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_revision_does_not_audit():
    session = MagicMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))
    audit = AsyncMock()
    with pytest.raises(RouteConflict):
        await deactivate_notification_route(
            session, tenant_id=uuid4(), channel="email", expected_revision=1,
            actor_id=uuid4(), authorized=True, audit=audit,
        )
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_conflict_rolls_back_and_does_not_commit(monkeypatch):
    from northstar_api.modules.platform_runtime import queue_notification_governance
    monkeypatch.setattr(
        queue_notification_governance, "deactivate_notification_route",
        AsyncMock(side_effect=RouteConflict("stale")),
    )
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await deactivate_platform_notification_route(
            "email", NotificationRouteDeactivateRequest(
                expected_revision=2, reason="Documented operations incident",
            ),
            SimpleNamespace(tenant_id=uuid4(), user_id=uuid4()), session,
        )
    assert error.value.status_code == 409
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_deactivation_api_commits_after_governance(monkeypatch):
    from northstar_api.modules.platform_runtime import queue_notification_governance
    service = AsyncMock(return_value=8)
    monkeypatch.setattr(queue_notification_governance, "deactivate_notification_route", service)
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    result = await deactivate_platform_notification_route(
        "webhook", NotificationRouteDeactivateRequest(
            expected_revision=7, reason="Incident containment decision",
        ),
        SimpleNamespace(tenant_id=uuid4(), user_id=uuid4()), session,
    )
    assert result == {"channel": "webhook", "revision": 8, "enabled": False}
    assert service.await_args.kwargs["expected_revision"] == 7
    session.commit.assert_awaited_once()
