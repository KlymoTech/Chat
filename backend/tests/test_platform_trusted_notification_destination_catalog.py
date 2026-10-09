"""Trusted destination catalog isolation and configuration qualification."""
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_secret_resolution import (
    DestinationBinding,
)
from northstar_api.modules.platform_runtime.trusted_notification_destination_catalog import (
    TrustedNotificationDestinationCatalog,
)


@pytest.mark.asyncio
async def test_exact_tenant_channel_reference_and_allowlist():
    tenant, other = uuid4(), uuid4()
    binding = DestinationBinding(
        tenant, "webhook", "approved:ops",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:ops",
        "hooks.example.test",
    )
    catalog = TrustedNotificationDestinationCatalog([binding])
    assert await catalog.lookup(tenant, "webhook", "approved:ops") == binding
    assert await catalog.lookup(other, "webhook", "approved:ops") is None
    assert await catalog.lookup(tenant, "email", "approved:ops") is None
    assert await catalog.lookup(tenant, "webhook", "approved:other") is None
    assert await catalog.lookup(tenant, "sms", "approved:ops") is None
    assert catalog.approved_secret_ids == frozenset({binding.secret_id})


def test_duplicate_binding_is_rejected():
    binding = DestinationBinding(uuid4(), "email", "approved:ops", "arn:aws:secretsmanager:us-east-1:123456789012:secret:ops")
    with pytest.raises(ValueError, match="duplicate"):
        TrustedNotificationDestinationCatalog([binding, binding])


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "internal.local", "hooks.example.test:8443"])
def test_unsafe_webhook_hosts_are_not_accepted(host):
    with pytest.raises(ValueError):
        TrustedNotificationDestinationCatalog([
            DestinationBinding(uuid4(), "webhook", "approved:ops", "arn:aws:secretsmanager:us-east-1:123456789012:secret:ops", host)
        ])


def test_email_binding_must_not_have_webhook_host():
    with pytest.raises(ValueError, match="email"):
        TrustedNotificationDestinationCatalog([
            DestinationBinding(uuid4(), "email", "approved:ops", "arn:aws:secretsmanager:us-east-1:123456789012:secret:ops", "hooks.example.test")
        ])
