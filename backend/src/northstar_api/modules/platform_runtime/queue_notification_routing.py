"""Fail-closed per-tenant notification transport routing.

The trusted configuration loader owns destination authorization and secret
retrieval. This router does not read HTTP input or select tenant endpoints.
Deployers must explicitly wire and enable it after integration qualification.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .queue_notification_dispatch import NotificationClaim, NotificationResult, NotificationTransport


class TenantTransportResolver(Protocol):
    async def resolve(self, tenant_id: UUID, channel: str) -> NotificationTransport | None: ...


class RoutedAlertNotificationTransport:
    def __init__(self, resolver: TenantTransportResolver) -> None:
        self._resolver = resolver

    async def send(self, notification: NotificationClaim) -> NotificationResult:
        if notification.channel not in {"email", "webhook"}:
            return NotificationResult(False)
        try:
            transport = await self._resolver.resolve(notification.tenant_id, notification.channel)
            if transport is None:
                return NotificationResult(False)
            result = await transport.send(notification)
        except Exception:
            # Never leak tenant configuration, URLs, SMTP details or secrets.
            return NotificationResult(False)
        if not isinstance(result, NotificationResult):
            return NotificationResult(False)
        return result


class StaticTenantTransportResolver:
    """Explicit immutable opt-in registry, useful for controlled deployments/tests.

    Never use shared default credentials or fallback across tenants/channels.
    """
    def __init__(self, transports: dict[tuple[UUID, str], NotificationTransport]) -> None:
        if any(channel not in {"email", "webhook"} for _, channel in transports):
            raise ValueError("unsupported notification channel")
        self._transports = dict(transports)

    async def resolve(self, tenant_id: UUID, channel: str) -> NotificationTransport | None:
        return self._transports.get((tenant_id, channel))
