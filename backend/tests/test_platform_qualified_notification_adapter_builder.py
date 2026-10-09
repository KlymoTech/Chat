"""Trusted provider builder rejects absent egress/tenant/provider configuration."""
from uuid import uuid4

import pytest

from northstar_api.email_config import EmailSettings
from northstar_api.modules.platform_runtime.qualified_notification_adapter_builder import (
    QualifiedNotificationAdapterBuilder,
)
from northstar_api.modules.platform_runtime.queue_notification_config import ApprovedNotificationRoute
from northstar_api.modules.platform_runtime.queue_notification_secret_resolution import (
    DestinationBinding, ResolvedDestination,
)
from northstar_api.modules.platform_runtime.signed_webhook_alert_transport import SignedWebhookAlertTransport


def pair(channel="webhook", hostname="hooks.example.test"):
    tenant = uuid4()
    route = ApprovedNotificationRoute(tenant, channel, "approved:ops", 2, True, True)
    destination = ResolvedDestination(
        DestinationBinding(tenant, channel, route.destination_reference, "vault:ops",
                           hostname if channel == "webhook" else None),
        b"x" * 32,
    )
    return route, destination


@pytest.mark.asyncio
async def test_webhook_builder_requires_explicit_egress_qualification():
    route, destination = pair()
    config = {(route.tenant_id, route.destination_reference): "https://hooks.example.test/alerts"}
    assert await QualifiedNotificationAdapterBuilder(webhook_urls=config).build_webhook(route, destination) is None
    builder = QualifiedNotificationAdapterBuilder(
        webhook_urls=config, webhook_egress_qualified=True,
    )
    assert isinstance(await builder.build_webhook(route, destination), SignedWebhookAlertTransport)


@pytest.mark.asyncio
async def test_cross_tenant_and_host_mismatch_fail_closed():
    route, destination = pair()
    config = {(uuid4(), route.destination_reference): "https://hooks.example.test/alerts"}
    builder = QualifiedNotificationAdapterBuilder(webhook_urls=config, webhook_egress_qualified=True)
    assert await builder.build_webhook(route, destination) is None
    config = {(route.tenant_id, route.destination_reference): "https://localhost/alerts"}
    builder = QualifiedNotificationAdapterBuilder(webhook_urls=config, webhook_egress_qualified=True)
    assert await builder.build_webhook(route, destination) is None


@pytest.mark.asyncio
async def test_email_requires_explicit_smtp_and_recipient_resolver():
    route, destination = pair("email")
    builder = QualifiedNotificationAdapterBuilder(webhook_urls={})
    assert await builder.build_email(route, destination) is None
    # Logging-only mode does not authorize sending even with a resolver.
    async def resolve(_claim):
        return "operator@example.test"
    builder = QualifiedNotificationAdapterBuilder(
        webhook_urls={}, smtp_settings=EmailSettings(email_delivery_mode="log"),
        recipient_resolver=resolve,
    )
    assert await builder.build_email(route, destination) is None


@pytest.mark.asyncio
async def test_wrong_channel_never_builds_transport():
    route, destination = pair("webhook")
    builder = QualifiedNotificationAdapterBuilder(
        webhook_urls={(route.tenant_id, route.destination_reference): "https://hooks.example.test/alerts"},
        webhook_egress_qualified=True,
    )
    assert await builder.build_email(route, destination) is None
