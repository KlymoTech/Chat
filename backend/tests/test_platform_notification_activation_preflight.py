"""Activation preflight only validates trusted configuration, never sends."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_activation_preflight import (
    TrustedNotificationActivationPreflight,
)
from northstar_api.modules.platform_runtime.queue_notification_config import ApprovedNotificationRoute
from northstar_api.modules.platform_runtime.queue_notification_secret_resolution import (
    DestinationBinding, ResolvedDestination,
)


def route(channel="webhook"):
    return ApprovedNotificationRoute(uuid4(), channel, "approved:ops", 3, False, True)


@pytest.mark.asyncio
async def test_webhook_needs_approved_egress():
    item = route()
    destination = ResolvedDestination(
        DestinationBinding(item.tenant_id, "webhook", "approved:ops",
                           "arn:aws:secretsmanager:us-east-1:123456789012:secret:ops",
                           "hooks.example.test"),
        b"x" * 32,
    )
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=destination))
    egress = SimpleNamespace(permits=AsyncMock(return_value=True))
    preflight = TrustedNotificationActivationPreflight(resolver, egress=egress)
    assert await preflight(item)
    assert resolver.resolve.await_args.args[0] == replace(item, enabled=True)
    egress.permits.assert_awaited_once_with(item.tenant_id, "hooks.example.test")


@pytest.mark.asyncio
async def test_missing_egress_blocks_webhook():
    item = route()
    destination = ResolvedDestination(
        DestinationBinding(item.tenant_id, "webhook", "approved:ops", "secret", "hooks.example.test"),
        b"x" * 32,
    )
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=destination))
    assert not await TrustedNotificationActivationPreflight(resolver)(item)


@pytest.mark.asyncio
async def test_missing_secret_blocks_email():
    item = route("email")
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=None))
    assert not await TrustedNotificationActivationPreflight(resolver)(item)


@pytest.mark.asyncio
async def test_unapproved_route_does_not_resolve():
    item = replace(route(), approved=False)
    resolver = SimpleNamespace(resolve=AsyncMock())
    assert not await TrustedNotificationActivationPreflight(resolver)(item)
    resolver.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_never_leaks_provider_message():
    item = route()
    resolver = SimpleNamespace(resolve=AsyncMock(side_effect=RuntimeError("credential=secret")))
    assert not await TrustedNotificationActivationPreflight(resolver)(item)
