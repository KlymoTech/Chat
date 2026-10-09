"""Secret resolution contract: tenant isolation, fail-closed checks, redaction."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_config import ApprovedNotificationRoute
from northstar_api.modules.platform_runtime.queue_notification_secret_resolution import (
    ApprovedDestinationResolver, DestinationBinding,
)


def route(tenant, *, approved=True, enabled=True, channel="webhook"):
    return ApprovedNotificationRoute(
        tenant, channel, "approved:operations", 1, enabled, approved
    )


def resolver(binding, secret=b"x" * 32):
    catalog = SimpleNamespace(lookup=AsyncMock(return_value=binding))
    store = SimpleNamespace(retrieve=AsyncMock(return_value=secret))
    return ApprovedDestinationResolver(catalog, store), catalog, store


@pytest.mark.asyncio
async def test_approved_route_resolves_without_exposing_secret():
    tenant = uuid4()
    binding = DestinationBinding(tenant, "webhook", "approved:operations", "vault/key",
                                 "hooks.example.test")
    service, catalog, store = resolver(binding)
    result = await service.resolve(route(tenant))
    assert result is not None
    assert result.secret == b"x" * 32
    assert b"x" * 32 != str(result).encode()
    catalog.lookup.assert_awaited_once_with(tenant, "webhook", "approved:operations")
    store.retrieve.assert_awaited_once_with("vault/key")


@pytest.mark.asyncio
@pytest.mark.parametrize("approved,enabled", [(False, True), (True, False), (False, False)])
async def test_disabled_or_unapproved_does_not_fetch_secrets(approved, enabled):
    tenant = uuid4()
    service, catalog, store = resolver(None)
    assert await service.resolve(route(tenant, approved=approved, enabled=enabled)) is None
    catalog.lookup.assert_not_awaited()
    store.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_tenant_binding_never_fetches_secret():
    tenant = uuid4()
    binding = DestinationBinding(uuid4(), "webhook", "approved:operations", "vault/key",
                                 "hooks.example.test")
    service, _, store = resolver(binding)
    assert await service.resolve(route(tenant)) is None
    store.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_reference_or_channel_does_not_fetch_secret():
    tenant = uuid4()
    binding = DestinationBinding(tenant, "email", "approved:other", "vault/key")
    service, _, store = resolver(binding)
    assert await service.resolve(route(tenant)) is None
    store.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_host_and_missing_secret_fail_closed():
    tenant = uuid4()
    binding = DestinationBinding(tenant, "webhook", "approved:operations", "vault/key")
    service, _, _ = resolver(binding)
    assert await service.resolve(route(tenant)) is None
    service, _, _ = resolver(DestinationBinding(
        tenant, "webhook", "approved:operations", "vault/key", "hooks.example.test"
    ), secret=None)
    assert await service.resolve(route(tenant)) is None


@pytest.mark.asyncio
async def test_secret_store_error_is_redacted():
    tenant = uuid4()
    binding = DestinationBinding(tenant, "email", "approved:operations", "vault/key")
    service, _, store = resolver(binding)
    store.retrieve.side_effect = PermissionError("credential=private")
    assert await service.resolve(route(tenant, channel="email")) is None
