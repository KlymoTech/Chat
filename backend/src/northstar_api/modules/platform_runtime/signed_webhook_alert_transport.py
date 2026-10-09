"""Opt-in, HMAC-signed operational alert webhook transport.

Destination and secret are provisioned by trusted platform configuration, not
the notification or HTTP request. Deploy with an egress allowlist for DNS
rebinding protection. No redirects, environment proxies, or secret logging.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from .queue_notification_dispatch import NotificationClaim, NotificationResult

WebhookClient = Callable[..., httpx.AsyncClient]


def validate_webhook_destination(url: str, allowed_host: str) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https" or not host or host != allowed_host.lower()
        or parsed.username is not None or parsed.password is not None
        or parsed.port not in (None, 443) or parsed.fragment
        or any(ch in url for ch in "\r\n\\")
        or host in {"localhost", "localhost.localdomain"}
        or host.endswith((".local", ".internal", ".localhost"))
    ):
        raise ValueError("webhook destination is not approved")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP-literal destinations are not permitted")


class SignedWebhookAlertTransport:
    def __init__(
        self,
        *,
        url: str,
        allowed_host: str,
        signing_key: bytes,
        client_factory: WebhookClient = httpx.AsyncClient,
        timeout_seconds: float = 5.0,
    ) -> None:
        validate_webhook_destination(url, allowed_host)
        if len(signing_key) < 32 or timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("invalid webhook signing key or timeout")
        self._url = url
        self._key = signing_key
        self._client_factory = client_factory
        self._timeout = timeout_seconds

    async def send(self, notification: NotificationClaim) -> NotificationResult:
        if notification.channel != "webhook":
            raise ValueError("webhook transport cannot send another channel")
        timestamp = str(int(datetime.now(UTC).timestamp()))
        body = json.dumps(
            {"schemaVersion": 1, "event": "queue.alert",
             "notificationId": str(notification.id),
             "tenantId": str(notification.tenant_id),
             "episodeId": str(notification.episode_id)},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(
            self._key, timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Northstar-Timestamp": timestamp,
            "X-Northstar-Signature": "sha256=" + signature,
            "X-Northstar-Delivery-ID": str(notification.id),
        }
        try:
            async with self._client_factory(
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(self._url, content=body, headers=headers)
        except (httpx.HTTPError, TimeoutError, OSError):
            return NotificationResult(False)
        # Only an explicit successful receiver response is acknowledgement.
        if not 200 <= response.status_code < 300:
            return NotificationResult(False)
        return NotificationResult(True, str(notification.id))
