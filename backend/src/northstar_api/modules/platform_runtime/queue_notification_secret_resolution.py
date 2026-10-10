"""Fail-closed secret-backed resolution for approved notification destinations.

Only a trusted backend composition root may supply the catalog and secret store.
No arbitrary network URL or secret path is accepted from notification payloads.
Production wiring and activation must pass independent egress/IAM qualification.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from .queue_notification_config import ApprovedNotificationRoute


@dataclass(frozen=True)
class DestinationBinding:
    tenant_id: UUID
    channel: str
    reference: str
    secret_id: str
    allowed_host: str | None = None

    def __post_init__(self) -> None:
        if self.channel not in {"email", "webhook"}:
            raise ValueError("unsupported destination channel")
        if not self.reference.startswith("approved:") or len(self.reference) <= 9:
            raise ValueError("destination requires approved reference")
        if not self.secret_id or any(ch.isspace() for ch in self.secret_id):
            raise ValueError("secret identifier required")


class DestinationCatalog(Protocol):
    async def lookup(self, tenant_id: UUID, channel: str, reference: str) -> DestinationBinding | None: ...


class SecretStore(Protocol):
    async def retrieve(self, secret_id: str) -> bytes | None: ...


@dataclass(frozen=True, repr=False)
class ResolvedDestination:
    binding: DestinationBinding
    secret: bytes

    def __repr__(self) -> str:
        return "ResolvedDestination(<redacted>)"


class ApprovedDestinationResolver:
    """Require exact tenant/channel/reference match and an approved enabled route."""

    def __init__(self, catalog: DestinationCatalog, secrets: SecretStore) -> None:
        self._catalog = catalog
        self._secrets = secrets

    async def resolve(self, route: ApprovedNotificationRoute) -> ResolvedDestination | None:
        if not route.enabled or not route.approved:
            return None
        if route.channel not in {"email", "webhook"}:
            return None
        try:
            binding = await self._catalog.lookup(
                route.tenant_id, route.channel, route.destination_reference
            )
            if (
                binding is None or binding.tenant_id != route.tenant_id
                or binding.channel != route.channel
                or binding.reference != route.destination_reference
            ):
                return None
            secret = await self._secrets.retrieve(binding.secret_id)
            if not isinstance(secret, bytes) or len(secret) < 32:
                return None
            if route.channel == "webhook" and not binding.allowed_host:
                return None
            return ResolvedDestination(binding=binding, secret=secret)
        except Exception:
            # Missing IAM permissions, secret rotation or provider failures
            # cannot silently select fallback tenant credentials.
            return None
