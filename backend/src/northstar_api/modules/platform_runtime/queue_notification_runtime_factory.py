"""Trusted runtime factory for approved notification delivery.

The factory constructs transports only for an enabled, approved route whose
tenant-scoped destination and secret resolve successfully. An explicitly
injected deployment adapter owns provider-specific configuration; this module
neither sends a message nor enables a notification worker.
"""
from __future__ import annotations

from typing import Protocol

from .queue_notification_config import ApprovedNotificationRoute
from .queue_notification_dispatch import NotificationTransport
from .queue_notification_secret_resolution import (
    ApprovedDestinationResolver,
    ResolvedDestination,
)
from .signed_webhook_alert_transport import validate_webhook_destination


class QualifiedNotificationTransportBuilder(Protocol):
    async def build_email(
        self, route: ApprovedNotificationRoute, destination: ResolvedDestination
    ) -> NotificationTransport | None: ...

    async def build_webhook(
        self, route: ApprovedNotificationRoute, destination: ResolvedDestination
    ) -> NotificationTransport | None: ...


class TrustedNotificationTransportFactory:
    """No global defaults, no cross-tenant credentials, no implicit provider."""

    def __init__(
        self,
        destinations: ApprovedDestinationResolver,
        builder: QualifiedNotificationTransportBuilder,
    ) -> None:
        self._destinations = destinations
        self._builder = builder

    async def create(
        self, route: ApprovedNotificationRoute
    ) -> NotificationTransport | None:
        if not route.enabled or not route.approved:
            return None
        if route.channel not in {"email", "webhook"}:
            return None
        try:
            resolved = await self._destinations.resolve(route)
            if resolved is None:
                return None
            binding = resolved.binding
            if (
                binding.tenant_id != route.tenant_id
                or binding.channel != route.channel
                or binding.reference != route.destination_reference
            ):
                return None
            if route.channel == "email":
                if binding.allowed_host is not None:
                    return None
                return await self._builder.build_email(route, resolved)
            if not binding.allowed_host:
                return None
            validate_webhook_destination(
                f"https://{binding.allowed_host}/", binding.allowed_host
            )
            return await self._builder.build_webhook(route, resolved)
        except Exception:
            # Misconfiguration and secret-store failures are non-delivery.
            # Secrets, endpoints, and credential errors must not be logged.
            return None
