"""Opt-in notification dispatch with atomic leases and bounded retries.

Delivery adapters are injected; no email or webhook implementation is enabled
here. Delivery is at-least-once: an ambiguous timeout may require retry, and
receivers must deduplicate using the stable notification id.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .queue_notification_persistence import QueueAlertNotification


@dataclass(frozen=True)
class NotificationClaim:
    id: UUID
    tenant_id: UUID
    episode_id: UUID
    channel: str
    lease_token: UUID
    attempts: int


@dataclass(frozen=True)
class NotificationResult:
    acknowledged: bool
    reference: str | None = None


class NotificationTransport(Protocol):
    async def send(self, notification: NotificationClaim) -> NotificationResult: ...


class NotificationDispatcher:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], transport: NotificationTransport,
        *, lease_seconds: int = 60, max_attempts: int = 8,
    ) -> None:
        if lease_seconds < 2 or max_attempts < 1:
            raise ValueError("invalid notification dispatch limits")
        self.sessions = sessions
        self.transport = transport
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    async def claim(self) -> NotificationClaim | None:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            record = await session.scalar(
                select(QueueAlertNotification)
                .where(
                    QueueAlertNotification.status.in_(("pending", "retrying", "leased")),
                    QueueAlertNotification.next_attempt_at <= now,
                    or_(QueueAlertNotification.lease_expires_at.is_(None),
                        QueueAlertNotification.lease_expires_at <= now),
                )
                .order_by(QueueAlertNotification.next_attempt_at, QueueAlertNotification.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            if record.attempts >= self.max_attempts:
                record.status = "exhausted"
                record.lease_token = None
                record.lease_expires_at = None
                return None
            token = uuid4()
            record.status = "leased"
            record.attempts += 1
            record.lease_token = token
            record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            return NotificationClaim(
                record.id, record.tenant_id, record.episode_id,
                record.channel, token, record.attempts,
            )

    async def dispatch_one(self) -> bool:
        claim = await self.claim()
        if claim is None:
            return False
        try:
            result = await self.transport.send(claim)
        except Exception:
            result = NotificationResult(False)
        acknowledged = result.acknowledged and bool(result.reference)
        now = datetime.now(UTC)
        next_state = ("delivered" if acknowledged else
                      "exhausted" if claim.attempts >= self.max_attempts else "retrying")
        delay = min(3600, 2 ** min(claim.attempts, 10))
        async with self.sessions() as session, session.begin():
            outcome = await session.execute(
                update(QueueAlertNotification)
                .where(
                    QueueAlertNotification.id == claim.id,
                    QueueAlertNotification.tenant_id == claim.tenant_id,
                    QueueAlertNotification.status == "leased",
                    QueueAlertNotification.lease_token == claim.lease_token,
                    QueueAlertNotification.lease_expires_at > now,
                )
                .values(
                    status=next_state,
                    delivered_at=now if acknowledged else None,
                    provider_reference=result.reference if acknowledged else None,
                    next_attempt_at=now + timedelta(seconds=delay),
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            return outcome.rowcount == 1
