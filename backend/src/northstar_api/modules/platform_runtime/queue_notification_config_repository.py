"""Read approved notification routes from authoritative persistent state."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .queue_notification_config import ApprovedNotificationRoute
from .queue_notification_config_persistence import ApprovedNotificationRouteRecord


class PostgresApprovedRouteRepository:
    """Tenant-scoped lookup; never fall back to another tenant or channel."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_route(self, tenant_id: UUID, channel: str) -> ApprovedNotificationRoute | None:
        if channel not in ("email", "webhook"):
            return None
        async with self.sessions() as session:
            record = await session.scalar(
                select(ApprovedNotificationRouteRecord).where(
                    ApprovedNotificationRouteRecord.tenant_id == tenant_id,
                    ApprovedNotificationRouteRecord.channel == channel,
                )
            )
        if record is None:
            return None
        return ApprovedNotificationRoute(
            tenant_id=record.tenant_id,
            channel=record.channel,
            destination_reference=record.destination_reference,
            revision=record.revision,
            enabled=record.enabled,
            approved=record.approved,
        )
