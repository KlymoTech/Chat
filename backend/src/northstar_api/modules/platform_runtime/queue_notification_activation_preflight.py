"""Read-only activation preflight for approved operational notification routes.

A disabled route is inspected using a temporary enabled candidate. Persistent
state is NOT changed until the activation service performs its fenced update.
No outbound SMTP or webhook request occurs during this preflight.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from .queue_notification_config import ApprovedNotificationRoute
from .queue_notification_secret_resolution import ApprovedDestinationResolver
from .signed_webhook_alert_transport import validate_webhook_destination


class EgressPolicy(Protocol):
    async def permits(self, tenant_id: object, host: str) -> bool: ...


class TrustedNotificationActivationPreflight:
    def __init__(
        self,
        destinations: ApprovedDestinationResolver,
        *,
        egress: EgressPolicy | None = None,
    ) -> None:
        self._destinations = destinations
        self._egress = egress

    async def __call__(self, route: ApprovedNotificationRoute) -> bool:
        if not route.approved or route.enabled:
            return False
        try:
            # Candidate is not stored; resolver intentionally requires enabled
            # routes during normal delivery and should not be weakened.
            candidate = replace(route, enabled=True)
            resolved = await self._destinations.resolve(candidate)
            if resolved is None:
                return False
            binding = resolved.binding
            if route.channel == "webhook":
                if self._egress is None or not binding.allowed_host:
                    return False
                validate_webhook_destination(
                    f"https://{binding.allowed_host}/", binding.allowed_host
                )
                return await self._egress.permits(route.tenant_id, binding.allowed_host) is True
            return route.channel == "email"
        except Exception:
            # Never expose IAM errors, hostnames or secret values to API clients.
            return False
