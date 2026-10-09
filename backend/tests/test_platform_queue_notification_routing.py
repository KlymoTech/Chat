"""Notification routing never falls back across tenants or channels."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_dispatch import (
    NotificationClaim, NotificationResult,
)
from northstar_api.modules.platform_runtime.queue_notification_routing import (
    RoutedAlertNotificationTransport, StaticTenantTransportResolver,
)


def claim(tenant, channel):
    return NotificationClaim(uuid4(), tenant, uuid4(), channel, uuid4(), 1)


@pytest.mark.asyncio
async def test_routes_only_to_matching_tenant_and_channel():
    tenant_a, tenant_b = uuid4(), uuid4()
    email = MagicMock(send=AsyncMock(return_value=NotificationResult(True, "smtp-receipt")))
    webhook = MagicMock(send=AsyncMock(return_value=NotificationResult(True, "webhook-receipt")))
    router = RoutedAlertNotificationTransport(
        StaticTenantTransportResolver({
            (tenant_a, "email"): email,
            (tenant_b, "webhook"): webhook,
        })
    )
    result_a = await router.send(claim(tenant_a, "email"))
    result_b = await router.send(claim(tenant_b, "webhook"))
    assert result_a.reference == "smtp-receipt"
    assert result_b.reference == "webhook-receipt"
    assert not (await router.send(claim(tenant_a, "webhook"))).acknowledged
    assert not (await router.send(claim(tenant_b, "email"))).acknowledged
    assert email.send.await_count == 1
    assert webhook.send.await_count == 1


@pytest.mark.asyncio
async def test_unknown_tenant_or_channel_returns_unacknowledged():
    tenant = uuid4()
    router = RoutedAlertNotificationTransport(StaticTenantTransportResolver({}))
    assert not (await router.send(claim(tenant, "email"))).acknowledged
    assert not (await router.send(claim(tenant, "sms"))).acknowledged


@pytest.mark.asyncio
async def test_transport_error_does_not_leak_configuration():
    tenant = uuid4()
    failed = MagicMock(send=AsyncMock(side_effect=RuntimeError("secret=hidden")))
    router = RoutedAlertNotificationTransport(
        StaticTenantTransportResolver({(tenant, "webhook"): failed})
    )
    result = await router.send(claim(tenant, "webhook"))
    assert result == NotificationResult(False)
    assert "secret" not in str(result)


@pytest.mark.asyncio
async def test_invalid_transport_response_is_not_accepted():
    tenant = uuid4()
    invalid = MagicMock(send=AsyncMock(return_value=True))
    router = RoutedAlertNotificationTransport(
        StaticTenantTransportResolver({(tenant, "email"): invalid})
    )
    assert not (await router.send(claim(tenant, "email"))).acknowledged


def test_registry_rejects_unsupported_channel():
    with pytest.raises(ValueError, match="unsupported"):
        StaticTenantTransportResolver({(uuid4(), "sms"): MagicMock()})
