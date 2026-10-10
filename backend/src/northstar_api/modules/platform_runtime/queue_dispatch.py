"""Lease-based, replayable dispatch for previously admitted platform jobs.

Runs as an explicit opt-in worker service; does not replace legacy Celery.
A lost broker acknowledgement may cause a duplicate publication: consumers
must deduplicate by job_id using authoritative durable state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .queue_contract import DeliveryOutcome, DurableJob, QueuePublisher, dispatch_committed_job
from .queue_persistence import DurableQueueRecord


@dataclass(frozen=True)
class ClaimedJob:
    job: DurableJob
    lease_token: UUID
    attempts: int


class DurableDispatchService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        publisher: QueuePublisher,
        *,
        lease_seconds: int = 60,
        max_attempts: int = 8,
    ) -> None:
        if lease_seconds < 2 or max_attempts < 1:
            raise ValueError("invalid dispatch safety parameters")
        self.sessions = sessions
        self.publisher = publisher
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    async def claim(self) -> ClaimedJob | None:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            stmt = (
                select(DurableQueueRecord)
                .where(
                    DurableQueueRecord.status.in_(("queued", "retrying", "leased")),
                    DurableQueueRecord.available_at <= now,
                    or_(
                        DurableQueueRecord.lease_expires_at.is_(None),
                        DurableQueueRecord.lease_expires_at <= now,
                    ),
                )
                .order_by(DurableQueueRecord.available_at, DurableQueueRecord.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            record = await session.scalar(stmt)
            if record is None:
                return None
            if record.attempts >= self.max_attempts:
                record.status = "dead_letter"
                record.lease_token = None
                record.lease_expires_at = None
                return None
            token = uuid4()
            record.attempts += 1
            record.lease_token = token
            record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            record.status = "leased"
            return ClaimedJob(
                DurableJob(
                    record.id, record.tenant_id, record.kind,
                    record.payload_reference, record.idempotency_key,
                ),
                token,
                record.attempts,
            )

    async def dispatch_one(self) -> bool:
        claim = await self.claim()
        if claim is None:
            return False
        try:
            receipt = await dispatch_committed_job(self.publisher, claim.job)
        except Exception:
            receipt = None
        now = datetime.now(UTC)
        accepted = receipt is not None and receipt.outcome is DeliveryOutcome.PUBLISHED
        # A definitive broker rejection is not a transient delivery failure:
        # quarantine the durable row for an explicitly audited manual replay.
        rejected = receipt is not None and receipt.outcome is DeliveryOutcome.REJECTED
        next_status = (
            "published" if accepted else
            "dead_letter" if rejected or claim.attempts >= self.max_attempts else
            "retrying"
        )
        retry_seconds = min(3600, 2 ** min(claim.attempts, 10))
        # Lease ownership is checked in SQL, so an expired prior owner cannot
        # overwrite a new worker's acknowledgement or retry status.
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                update(DurableQueueRecord)
                .where(
                    DurableQueueRecord.id == claim.job.job_id,
                    DurableQueueRecord.lease_token == claim.lease_token,
                    DurableQueueRecord.status == "leased",
                    DurableQueueRecord.lease_expires_at > now,
                )
                .values(
                    status=next_status,
                    published_reference=receipt.reference if accepted else None,
                    available_at=now + timedelta(seconds=retry_seconds),
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
        # If the lease expired or another worker owns the row, the database
        # did not record an outcome. Do not report successful progress.
        return result.rowcount == 1
