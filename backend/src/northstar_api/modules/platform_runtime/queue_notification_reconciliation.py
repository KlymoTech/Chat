"""Bounded reconciliation of expired notification leases.

A stale in-flight claim cannot be safely assumed delivered. Expired records
return to retrying or are exhausted without deleting their history. Recovery
never invokes external transports and is safe for concurrent reconcilers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .queue_notification_persistence import QueueAlertNotification


@dataclass(frozen=True)
class ReconciliationResult:
    retried: int = 0
    exhausted: int = 0


class NotificationLeaseReconciler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        max_attempts: int = 8,
        batch_size: int = 100,
    ) -> None:
        if max_attempts < 1 or not 1 <= batch_size <= 1000:
            raise ValueError("invalid reconciliation limits")
        self.sessions = sessions
        self.max_attempts = max_attempts
        self.batch_size = batch_size

    async def reconcile_once(self, *, tenant_id: UUID | None = None) -> ReconciliationResult:
        now = datetime.now(UTC)
        retried = exhausted = 0
        async with self.sessions() as session, session.begin():
            query = (
                select(QueueAlertNotification)
                .where(
                    QueueAlertNotification.status == "leased",
                    QueueAlertNotification.lease_expires_at <= now,
                    QueueAlertNotification.lease_token.is_not(None),
                )
                .order_by(QueueAlertNotification.lease_expires_at, QueueAlertNotification.id)
                .with_for_update(skip_locked=True)
                .limit(self.batch_size)
            )
            if tenant_id is not None:
                query = query.where(QueueAlertNotification.tenant_id == tenant_id)
            records = (await session.scalars(query)).all()
            for record in records:
                if record.attempts >= self.max_attempts:
                    record.status = "exhausted"
                    exhausted += 1
                else:
                    record.status = "retrying"
                    retried += 1
                record.lease_token = None
                record.lease_expires_at = None
                # Do not reset attempts, delivered_at or provider_reference.
                # next_attempt_at is the persisted retry schedule.
        return ReconciliationResult(retried, exhausted)
