"""Admin activation is deny-by-default and transactionally governed."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.super_admin.api import runtime


def record(tenant, proposer, approver):
    return SimpleNamespace(
        tenant_id=tenant, channel="webhook", destination_reference="approved:ops",
        revision=4, approved=True, enabled=False,
        proposed_by=proposer, approved_by=approver,
    )


def db(value):
    session = MagicMock()
    session.scalar = AsyncMock(return_value=value)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def payload():
    return runtime.NotificationRouteActivateRequest(
        expected_revision=4, reason="Reviewed and approved operations destination",
    )


def test_default_activation_preflight_is_unavailable():
    with pytest.raises(HTTPException) as error:
        runtime.get_notification_activation_preflight()
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_tenant_scope_required_before_database_read():
    session = db(None)
    with pytest.raises(HTTPException) as error:
        await runtime.activate_platform_notification_route(
            "webhook", payload(), SimpleNamespace(tenant_id=None, user_id=uuid4()),
            session, AsyncMock(return_value=True),
        )
    assert error.value.status_code == 403
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_independent_approval_blocks_activation():
    tenant, proposer = uuid4(), uuid4()
    session = db(record(tenant, proposer, proposer))
    preflight = AsyncMock(return_value=True)
    with pytest.raises(HTTPException) as error:
        await runtime.activate_platform_notification_route(
            "webhook", payload(), SimpleNamespace(tenant_id=tenant, user_id=uuid4()),
            session, preflight,
        )
    assert error.value.status_code == 409
    preflight.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_trusted_preflight_success_commits_audited_activation(monkeypatch):
    tenant = uuid4()
    session = db(record(tenant, uuid4(), uuid4()))
    preflight = AsyncMock(return_value=True)
    from northstar_api.modules.platform_runtime import queue_notification_activation
    service = AsyncMock(return_value=5)
    monkeypatch.setattr(queue_notification_activation, "activate_notification_route", service)
    principal = SimpleNamespace(tenant_id=tenant, user_id=uuid4())
    result = await runtime.activate_platform_notification_route(
        "webhook", payload(), principal, session, preflight,
    )
    assert result == {"channel": "webhook", "revision": 5, "enabled": True}
    assert service.await_args.kwargs["preflight"] is preflight
    assert service.await_args.kwargs["route"].tenant_id == tenant
    assert tenant in session.scalar.await_args.args[0].compile().params.values()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_preflight_conflict_rolls_back(monkeypatch):
    tenant = uuid4()
    session = db(record(tenant, uuid4(), uuid4()))
    from northstar_api.modules.platform_runtime import queue_notification_activation
    from northstar_api.modules.platform_runtime.queue_notification_governance import RouteConflict
    monkeypatch.setattr(
        queue_notification_activation, "activate_notification_route",
        AsyncMock(side_effect=RouteConflict("preflight failed")),
    )
    with pytest.raises(HTTPException) as error:
        await runtime.activate_platform_notification_route(
            "webhook", payload(), SimpleNamespace(tenant_id=tenant, user_id=uuid4()),
            session, AsyncMock(return_value=False),
        )
    assert error.value.status_code == 409
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
