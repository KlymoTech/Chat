"""Signed webhook delivery contract: destination, signature, and failure safety."""
import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest

from northstar_api.modules.platform_runtime.queue_notification_dispatch import NotificationClaim
from northstar_api.modules.platform_runtime.signed_webhook_alert_transport import (
    SignedWebhookAlertTransport, validate_webhook_destination,
)


def claim(channel="webhook"):
    return NotificationClaim(uuid4(), uuid4(), uuid4(), channel, uuid4(), 1)


def transport(handler):
    def client_factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    return SignedWebhookAlertTransport(
        url="https://hooks.example.test/alerts", allowed_host="hooks.example.test",
        signing_key=b"k" * 32, client_factory=client_factory,
    )


@pytest.mark.asyncio
async def test_signature_and_delivery_reference():
    item = claim()
    def receiver(request):
        payload = json.loads(request.content)
        assert payload["notificationId"] == str(item.id)
        assert request.headers["X-Northstar-Delivery-ID"] == str(item.id)
        timestamp = request.headers["X-Northstar-Timestamp"]
        expected = hmac.new(b"k" * 32, timestamp.encode() + b"." + request.content, hashlib.sha256)
        assert hmac.compare_digest(
            request.headers["X-Northstar-Signature"], "sha256=" + expected.hexdigest()
        )
        return httpx.Response(204)
    result = await transport(receiver).send(item)
    assert result.acknowledged
    assert result.reference == str(item.id)


@pytest.mark.asyncio
async def test_redirect_is_not_followed_and_not_acknowledged():
    called = []
    def receiver(request):
        called.append(request.url)
        return httpx.Response(302, headers={"Location": "https://evil.example/collect"})
    result = await transport(receiver).send(claim())
    assert not result.acknowledged
    assert len(called) == 1


@pytest.mark.asyncio
async def test_provider_error_is_retryable():
    result = await transport(lambda request: httpx.Response(503)).send(claim())
    assert not result.acknowledged


@pytest.mark.asyncio
async def test_wrong_channel_fails_before_http():
    with pytest.raises(ValueError, match="another channel"):
        await transport(lambda request: httpx.Response(204)).send(claim("email"))


@pytest.mark.parametrize("url,host", [
    ("http://hooks.example.test/alerts", "hooks.example.test"),
    ("https://localhost/a", "localhost"),
    ("https://127.0.0.1/a", "127.0.0.1"),
    ("https://hooks.example.test:8443/a", "hooks.example.test"),
    ("https://hooks.example.test.evil.test/a", "hooks.example.test"),
    ("https://user:pass@hooks.example.test/a", "hooks.example.test"),
])
def test_invalid_destination_rejected(url, host):
    with pytest.raises(ValueError, match="not approved|not permitted"):
        validate_webhook_destination(url, host)


def test_short_signing_key_rejected():
    with pytest.raises(ValueError, match="signing key"):
        SignedWebhookAlertTransport(
            url="https://hooks.example.test/alerts",
            allowed_host="hooks.example.test", signing_key=b"short",
        )
