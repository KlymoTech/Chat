"""Opt-in SMTP adapter for durable operational queue alerts.

Application wiring must provide an authorized tenant-scoped recipient resolver.
No recipient is inferred from user input or the alert row itself. Existing
SMTP configuration and secure secret handling remain authoritative.
"""
from __future__ import annotations

import asyncio
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Awaitable, Callable

from northstar_api.email_config import EmailSettings
from northstar_api.services.smtp import smtp_send

from .queue_notification_dispatch import NotificationClaim, NotificationResult

RecipientResolver = Callable[[NotificationClaim], Awaitable[str | None]]
SendEmail = Callable[[EmailMessage, EmailSettings], None]


class SmtpAlertNotificationTransport:
    """Send a minimal incident pointer; no tenant message content is emailed."""

    def __init__(
        self,
        *,
        settings: EmailSettings,
        resolve_recipient: RecipientResolver,
        sender: SendEmail = smtp_send,
        timeout_seconds: float = 15.0,
    ) -> None:
        if settings.email_delivery_mode != "smtp" or not settings.smtp_host.strip():
            raise ValueError("SMTP alert delivery requires explicitly enabled SMTP configuration")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._settings = settings
        self._resolve_recipient = resolve_recipient
        self._sender = sender
        self._timeout = timeout_seconds

    async def send(self, notification: NotificationClaim) -> NotificationResult:
        if notification.channel != "email":
            raise ValueError("SMTP adapter cannot dispatch a non-email notification")
        recipient = await self._resolve_recipient(notification)
        if not recipient or any(ch in recipient for ch in "\r\n") or "@" not in recipient:
            # Fail closed. Never redirect an incident to an arbitrary fallback.
            return NotificationResult(False)

        message = EmailMessage()
        message["From"] = self._settings.email_from_address
        message["To"] = recipient
        message["Subject"] = "Northstar operational queue alert"
        # Stable across retries; supports downstream duplicate suppression.
        reference = f"<northstar-alert-{notification.id}@notification.northstar.local>"
        message["Message-ID"] = reference
        message.set_content(
            "An operational alert requires review in the authenticated "
            "Northstar platform administration console.\n"
            f"Notification reference: {notification.id}\n"
        )
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._sender, message, self._settings),
                timeout=self._timeout,
            )
        except Exception:
            # SMTP acknowledgement may be lost; idempotent downstream handling
            # is required. Never record delivered after an uncertain result.
            return NotificationResult(False)
        return NotificationResult(True, reference)
