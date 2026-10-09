"""Explicitly provisioned adapters for the approved notification runtime factory.

Configuration is supplied by the deployment composition root, never by queue
payloads. These constructors do not start workers or send notifications.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from northstar_api.email_config import EmailSettings

from .queue_notification_config import ApprovedNotificationRoute
from .queue_notification_dispatch import NotificationClaim, NotificationTransport
from .queue_notification_secret_resolution import ResolvedDestination
from .signed_webhook_alert_transport import (
    SignedWebhookAlertTransport,
    validate_webhook_destination,
)
from .smtp_alert_transport import SmtpAlertNotificationTransport


class QualifiedNotificationAdapterBuilder:
    def __init__(
        self,
        *,
        webhook_urls: dict[tuple[UUID, str], str],
        smtp_settings: EmailSettings | None = None,
        recipient_resolver: Callable[[NotificationClaim], Awaitable[str | None]] | None = None,
        webhook_egress_qualified: bool = False,
    ) -> None:
        # A hostname check alone cannot prevent DNS rebinding. Egress must be
        # independently qualified by deployment policy before any webhook use.
        self._webhook_urls = dict(webhook_urls)
        self._smtp_settings = smtp_settings
        self._recipient_resolver = recipient_resolver
        self._egress_qualified = webhook_egress_qualified

    async def build_email(
        self, route: ApprovedNotificationRoute, destination: ResolvedDestination
    ) -> NotificationTransport | None:
        if (
            route.channel != "email"
            or destination.binding.channel != "email"
            or destination.binding.tenant_id != route.tenant_id
            or destination.binding.reference != route.destination_reference
            or destination.binding.allowed_host is not None
            or self._smtp_settings is None
            or self._recipient_resolver is None
        ):
            return None
        # SMTP passwords remain under the existing settings/secret governance.
        # Do not substitute webhook HMAC key material for SMTP credentials.
        try:
            return SmtpAlertNotificationTransport(
                settings=self._smtp_settings,
                resolve_recipient=self._recipient_resolver,
            )
        except ValueError:
            return None

    async def build_webhook(
        self, route: ApprovedNotificationRoute, destination: ResolvedDestination
    ) -> NotificationTransport | None:
        binding = destination.binding
        if (
            not self._egress_qualified
            or route.channel != "webhook"
            or binding.channel != "webhook"
            or binding.tenant_id != route.tenant_id
            or binding.reference != route.destination_reference
            or not binding.allowed_host
        ):
            return None
        url = self._webhook_urls.get((route.tenant_id, route.destination_reference))
        if url is None:
            return None
        try:
            validate_webhook_destination(url, binding.allowed_host)
            return SignedWebhookAlertTransport(
                url=url,
                allowed_host=binding.allowed_host,
                signing_key=destination.secret,
            )
        except ValueError:
            return None
