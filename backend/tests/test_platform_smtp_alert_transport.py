"""SMTP operational alert adapter contract tests; never use live SMTP."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.email_config import EmailSettings
from northstar_api.modules.platform_runtime.queue_notification_dispatch import NotificationClaim
from northstar_api.modules.platform_runtime.smtp_alert_transport import SmtpAlertNotificationTransport


def claim(channel="email"):
    return NotificationClaim(uuid4(), uuid4(), uuid4(), channel, uuid4(), 1)


def smtp_settings():
    return EmailSettings(
        email_delivery_mode="smtp", smtp_host="smtp.internal.test",
        email_from_address="alerts@example.test", smtp_ssl=False,
        smtp_starttls=True,
    )


@pytest.mark.asyncio
async def test_smtp_ack_contains_stable_reference_without_incident_details():
    sender = MagicMock()
    resolver = AsyncMock(return_value="operator@example.test")
    item = claim()
    transport = SmtpAlertNotificationTransport(
        settings=smtp_settings(), resolve_recipient=resolver, sender=sender,
    )
    result = await transport.send(item)
    assert result.acknowledged
    assert str(item.id) in result.reference
    resolver.assert_awaited_once_with(item)
    message = sender.call_args.args[0]
    assert message["To"] == "operator@example.test"
    assert message["From"] == "alerts@example.test"
    assert message["Message-ID"] == result.reference
    assert str(item.tenant_id) not in message.get_content()


@pytest.mark.asyncio
async def test_missing_recipient_does_not_send():
    sender = MagicMock()
    transport = SmtpAlertNotificationTransport(
        settings=smtp_settings(), resolve_recipient=AsyncMock(return_value=None),
        sender=sender,
    )
    assert not (await transport.send(claim())).acknowledged
    sender.assert_not_called()


@pytest.mark.asyncio
async def test_smtp_exception_remains_retryable_without_leaking_secret():
    sender = MagicMock(side_effect=OSError("sensitive-credentials"))
    transport = SmtpAlertNotificationTransport(
        settings=smtp_settings(),
        resolve_recipient=AsyncMock(return_value="operator@example.test"),
        sender=sender,
    )
    result = await transport.send(claim())
    assert not result.acknowledged
    assert result.reference is None


@pytest.mark.asyncio
async def test_wrong_channel_never_resolves_recipient():
    resolver = AsyncMock()
    transport = SmtpAlertNotificationTransport(
        settings=smtp_settings(), resolve_recipient=resolver, sender=MagicMock(),
    )
    with pytest.raises(ValueError, match="non-email"):
        await transport.send(claim("webhook"))
    resolver.assert_not_awaited()


def test_log_only_delivery_mode_is_not_accepted():
    with pytest.raises(ValueError, match="explicitly enabled"):
        SmtpAlertNotificationTransport(
            settings=EmailSettings(email_delivery_mode="log"),
            resolve_recipient=AsyncMock(),
        )
