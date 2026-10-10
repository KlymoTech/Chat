"""Trusted, fail-closed notification routing configuration.

The repository and factory are injected by a privileged composition root.
This module never accepts destinations from an alert payload, decrypts secrets,
or activates live delivery by itself. A versioned enabled policy is required.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from .queue_notification_dispatch import NotificationTransport
from .queue_notification_routing import TenantTransportResolver


@dataclass(frozen=True)
class ApprovedNotificationRoute:
    tenant_id: UUID
    channel: str
    destination_reference: str
    revision: int
    enabled: bool
    approved: bool

    def __post_init__(self) -> None:
        if self.channel not in ("email", "webhook"):
            raise ValueError("unsupported channel")
        if self.revision < 1:
            raise ValueError("route revision must be positive")
        if (not self.destination_reference.startswith("approved:") or len(self.destination_reference) <= len("approved:") or len(self.destination_reference) > 200 or any(ch.isspace() for ch in self.destination_reference)):
            raise ValueError("route must use a bounded approved destination reference")


class ApprovedRouteRepository(Protocol):
    async def get_route(self, tenant_id: UUID, channel: str) -> ApprovedNotificationRoute | None: ...


class ApprovedTransportFactory(Protocol):
    async def create(self, route: ApprovedNotificationRoute) -> NotificationTransport | None: ...


class ApprovedTenantTransportResolver(TenantTransportResolver):
    """Require exact tenant/channel match and explicit approval at resolution time."""

    def __init__(self, routes: ApprovedRouteRepository, factory: ApprovedTransportFactory) -> None:
        self._routes = routes
        self._factory = factory

    async def resolve(self, tenant_id: UUID, channel: str) -> NotificationTransport | None:
        if channel not in ("email", "webhook"):
            return None
        route = await self._routes.get_route(tenant_id, channel)
        if route is None or route.tenant_id != tenant_id or route.channel != channel:
            return None
        if not route.enabled or not route.approved:
            return None
        return await self._factory.create(route)
