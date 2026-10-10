"""Read-only queue health assessment from authoritative persisted job state.

Job-state health is distinct from external SQS/RabbitMQ broker health.
The endpoint must never report a healthy broker without an independent probe.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .queue_persistence import DurableQueueRecord


@dataclass(frozen=True)
class QueueHealth:
    tenant_id: UUID
    status: str
    counts: dict[str, int]
    overdue: int
    stale_leases: int
    oldest_pending_seconds: int | None
    broker_health: str = "unknown"

    def as_json(self) -> dict[str, object]:
        data = asdict(self)
        data["tenant_id"] = str(self.tenant_id)
        return data


async def assess_queue_health(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    now: datetime | None = None,
    age_limit_seconds: int = 300,
) -> QueueHealth:
    """Evaluate only the authorized tenant's rows without mutating them."""
    if age_limit_seconds < 1:
        raise ValueError("age limit must be positive")
    clock = now or datetime.now(UTC)
    statuses = ("queued", "retrying", "leased", "published", "dead_letter")
    counts = {name: 0 for name in statuses}
    results = await session.execute(
        select(DurableQueueRecord.status, func.count(DurableQueueRecord.id))
        .where(DurableQueueRecord.tenant_id == tenant_id)
        .group_by(DurableQueueRecord.status)
    )
    for status, count in results.all():
        counts[str(status)] = int(count)
    overdue = int(await session.scalar(
        select(func.count(DurableQueueRecord.id)).where(
            DurableQueueRecord.tenant_id == tenant_id,
            DurableQueueRecord.status.in_(("queued", "retrying")),
            DurableQueueRecord.available_at < clock - timedelta(seconds=age_limit_seconds),
        )
    ) or 0)
    stale_leases = int(await session.scalar(
        select(func.count(DurableQueueRecord.id)).where(
            DurableQueueRecord.tenant_id == tenant_id,
            DurableQueueRecord.status == "leased",
            DurableQueueRecord.lease_expires_at < clock,
        )
    ) or 0)
    oldest = await session.scalar(
        select(func.min(DurableQueueRecord.created_at)).where(
            DurableQueueRecord.tenant_id == tenant_id,
            DurableQueueRecord.status.in_(("queued", "retrying", "leased")),
        )
    )
    if oldest is not None:
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        age = max(0, int((clock - oldest).total_seconds()))
    else:
        age = None
    if stale_leases or overdue or counts["dead_letter"]:
        status = "degraded"
    elif sum(counts.values()) == 0:
        status = "empty"
    else:
        status = "operational"
    return QueueHealth(tenant_id, status, counts, overdue, stale_leases, age)
