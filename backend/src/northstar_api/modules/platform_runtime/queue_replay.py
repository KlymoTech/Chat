"""Audited, tenant-scoped queue reconciliation and controlled dead-letter replay.

This service is only callable by a trusted application boundary that has
already authenticated and authorized the operator. It is not an HTTP endpoint.
Published and leased jobs are never automatically replayed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .queue_persistence import DurableQueueRecord


class ReplayConflict(ValueError):
    """The requested dead-letter replay is not permitted."""


@dataclass(frozen=True)
class ReplayDecision:
    job_id: UUID
    tenant_id: UUID
    accepted: bool
    reason: str


class QueueReplayService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def replay_dead_letter(
        self,
        *,
        job_id: UUID,
        tenant_id: UUID,
        operator_id: UUID,
        authorized: bool,
        reason: str,
        audit_callback,
    ) -> ReplayDecision:
        if not authorized:
            raise PermissionError("queue replay requires explicit operator authorization")
        if not reason.strip() or len(reason.strip()) < 12 or len(reason) > 500:
            raise ValueError("queue replay requires a documented reason")
        if audit_callback is None:
            raise ValueError("queue replay requires a transactional audit callback")

        now = datetime.now(UTC)
        async with self.sessions() as session:
            async with session.begin():
                # Restrict state transitions with a database-side CAS: no
                # cross-tenant operation or replay of published/inflight work.
                outcome = await session.execute(
                    update(DurableQueueRecord)
                    .where(
                        DurableQueueRecord.id == job_id,
                        DurableQueueRecord.tenant_id == tenant_id,
                        DurableQueueRecord.status == "dead_letter",
                        DurableQueueRecord.lease_token.is_(None),
                    )
                    .values(
                        status="queued",
                        attempts=0,
                        available_at=now,
                        published_reference=None,
                        lease_expires_at=None,
                    )
                )
                if outcome.rowcount != 1:
                    raise ReplayConflict("job is not eligible for tenant-scoped dead-letter replay")
                # Callback must write an audit row in this same transaction.
                # Failure raises, rolling back the state transition.
                await audit_callback(
                    session,
                    {
                        "action": "platform.queue.dead_letter_replayed",
                        "job_id": str(job_id),
                        "tenant_id": str(tenant_id),
                        "operator_id": str(operator_id),
                        "reason": reason.strip(),
                    },
                )
        return ReplayDecision(job_id, tenant_id, True, "queued_for_reconciliation")
