"""Qualified runtime factory cannot silently select another tenant's provider."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_config import ApprovedNotificationRoute
from northstar_api.modules.platform_runtime.queue_notification_runtime_factory import (
    TrustedNotificationTransportFactory,
)
from northstar_api.modules.platform_runtime.queue_notification_secret_resolution import (
    DestinationBinding, ResolvedDestination,
)


def route(channel="webhook", *, enabled=True, approved=True):
    return ApprovedNotificationRoute(uuid4(), channel, "approved:ops", 3, enabled, approved)


def setup(binding):
    destination = SimpleNamespace(resolve=AsyncMock(return_value=binding))
    builder = SimpleNamespace(build_email=AsyncMock(return_value=object()),
                              build_webhook=AsyncMock(return_value=object()))
    return TrustedNotificationTransportFactory(destination, builder), destination, builder


@pytest.mark.asyncio
async def test_enabled_approved_webhook_uses_matching_destination():
    item = route()
    binding = DestinationBinding(
        item.tenant_id, "webhook", item.destination_reference, "vault:key",
        "hooks.example.test",
    )
    factory, resolver, builder = setup(ResolvedDestination(binding, b"x" * 32))
    assert await factory.create(item) is builder.build_webhook.return_value
    resolver.resolve.assert_awaited_once_with(item)
    builder.build_webhook.assert_awaited_once()
    builder.build_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_only_uses_email_builder():
    item = route("email")
    binding = DestinationBinding(item.tenant_id, "email", item.destination_reference, "vault:key")
    factory, _, builder = setup(ResolvedDestination(binding, b"x" * 32))
    assert await factory.create(item) is builder.build_email.return_value
    builder.build_webhook.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,approved", [(False, True), (True, False)])
async def test_disabled_or_unapproved_skips_secrets(enabled, approved):
    factory, resolver, builder = setup(None)
    assert await factory.create(route(enabled=enabled, approved=approved)) is None
    resolver.resolve.assert_not_awaited()
    builder.build_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_tenant_binding_is_rejected():
    item = route()
    binding = DestinationBinding(uuid4(), "webhook", item.destination_reference,
                                 "vault:key", "hooks.example.test")
    factory, _, builder = setup(ResolvedDestination(binding, b"x" * 32))
    assert await factory.create(item) is None
    builder.build_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_secret_failure_returns_no_transport():
    item = route()
    factory, resolver, builder = setup(None)
    resolver.resolve.side_effect = RuntimeError("private secret")
    assert await factory.create(item) is None
    builder.build_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_disallowed_host_prevents_webhook_builder():
    item = route()
    binding = DestinationBinding(item.tenant_id, "webhook", item.destination_reference,
                                 "vault:key", "localhost")
    factory, _, builder = setup(ResolvedDestination(binding, b"x" * 32))
    assert await factory.create(item) is None
    builder.build_webhook.assert_not_awaited()
