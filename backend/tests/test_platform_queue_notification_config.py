"""Approved route configuration never falls back between tenants/channels."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_config import (
    ApprovedNotificationRoute,
    ApprovedTenantTransportResolver,
)


def route(tenant, channel="email", *, enabled=True, approved=True):
    return ApprovedNotificationRoute(
        tenant_id=tenant,
        channel=channel,
        destination_reference="approved:ops-primary",
        revision=1,
        enabled=enabled,
        approved=approved,
    )


@pytest.mark.asyncio
async def test_approved_matching_route_builds_transport():
    tenant = uuid4()
    policy = route(tenant)
    transport = object()
    repo = SimpleNamespace(get_route=AsyncMock(return_value=policy))
    factory = SimpleNamespace(create=AsyncMock(return_value=transport))
    resolver = ApprovedTenantTransportResolver(repo, factory)
    assert await resolver.resolve(tenant, "email") is transport
    repo.get_route.assert_awaited_once_with(tenant, "email")
    factory.create.assert_awaited_once_with(policy)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,approved", [(False, True), (True, False), (False, False)])
async def test_disabled_or_unapproved_routes_cannot_dispatch(enabled, approved):
    tenant = uuid4()
    repo = SimpleNamespace(get_route=AsyncMock(return_value=route(tenant, enabled=enabled, approved=approved)))
    factory = SimpleNamespace(create=AsyncMock())
    assert await ApprovedTenantTransportResolver(repo, factory).resolve(tenant, "email") is None
    factory.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_tenant_or_channel_is_rejected():
    tenant = uuid4()
    repo = SimpleNamespace(get_route=AsyncMock(return_value=route(uuid4())))
    factory = SimpleNamespace(create=AsyncMock())
    resolver = ApprovedTenantTransportResolver(repo, factory)
    assert await resolver.resolve(tenant, "email") is None
    repo.get_route.return_value = route(tenant, "webhook")
    assert await resolver.resolve(tenant, "email") is None
    factory.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_channel_skips_repository():
    repo = SimpleNamespace(get_route=AsyncMock())
    factory = SimpleNamespace(create=AsyncMock())
    assert await ApprovedTenantTransportResolver(repo, factory).resolve(uuid4(), "sms") is None
    repo.get_route.assert_not_awaited()


def test_invalid_route_policy_is_rejected():
    tenant = uuid4()
    with pytest.raises(ValueError, match="approved"):
        ApprovedNotificationRoute(tenant, "email", "https://external.example", 1, True, True)
    with pytest.raises(ValueError, match="revision"):
        ApprovedNotificationRoute(tenant, "email", "approved:ops", 0, True, True)
    with pytest.raises(ValueError, match="channel"):
        ApprovedNotificationRoute(tenant, "sms", "approved:ops", 1, True, True)
