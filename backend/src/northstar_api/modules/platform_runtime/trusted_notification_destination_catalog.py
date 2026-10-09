"""Immutable trusted destination catalog for operational alert routes.

Only a deployment-controlled composition root provides bindings. This catalog
never accepts records from notification payloads or untrusted HTTP requests.
No shared tenant fallback exists; changes require a reviewed deployment.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Iterable
from uuid import UUID

from .queue_notification_secret_resolution import DestinationBinding
from .signed_webhook_alert_transport import validate_webhook_destination


class TrustedNotificationDestinationCatalog:
    def __init__(self, bindings: Iterable[DestinationBinding]) -> None:
        entries: dict[tuple[UUID, str, str], DestinationBinding] = {}
        for binding in bindings:
            if not isinstance(binding, DestinationBinding):
                raise ValueError("catalog entries must be validated destination bindings")
            if binding.channel == "webhook":
                if not binding.allowed_host:
                    raise ValueError("webhook binding requires an approved hostname")
                # Validate the host against the existing SSRF policy before
                # accepting it as trusted deployment configuration.
                validate_webhook_destination(
                    f"https://{binding.allowed_host}/", binding.allowed_host
                )
            elif binding.allowed_host is not None:
                raise ValueError("email bindings must not define webhook host policy")
            key = (binding.tenant_id, binding.channel, binding.reference)
            if key in entries:
                raise ValueError("duplicate tenant/channel/destination reference")
            entries[key] = binding
        self._entries = MappingProxyType(entries)

    async def lookup(
        self, tenant_id: UUID, channel: str, reference: str
    ) -> DestinationBinding | None:
        if channel not in {"email", "webhook"}:
            return None
        return self._entries.get((tenant_id, channel, reference))

    @property
    def approved_secret_ids(self) -> frozenset[str]:
        """Use as the explicit AWS Secrets Manager adapter allowlist."""
        return frozenset(binding.secret_id for binding in self._entries.values())
