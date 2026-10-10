"""PostgreSQL-backed idempotent durable job admission.

This additive adapter is not wired into the legacy dispatcher. Each call owns a
database transaction; no broker publish occurs before database commit.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.modules.platform_runtime.queue_contract import DurableJob, QueueAdmissionError
from northstar_api.modules.platform_runtime.queue_persistence import DurableQueueRecord


class PostgresDurableJobStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def accept(self, job: DurableJob) -> bool:
        async with self._sessions() as session:
            async with session.begin():
                values = dict(
                    id=job.job_id,
                    tenant_id=job.tenant_id,
                    kind=job.kind,
                    payload_reference=job.payload_reference,
                    idempotency_key=job.idempotency_key,
                    status="queued",
                )
                dialect = session.bind.dialect.name if session.bind else ""
                if dialect == "postgresql":
                    statement = pg_insert(DurableQueueRecord).values(**values)
                elif dialect == "sqlite":
                    statement = sqlite_insert(DurableQueueRecord).values(**values)
                else:
                    raise QueueAdmissionError("durable queue requires PostgreSQL or test SQLite")
                result = await session.execute(
                    statement.on_conflict_do_nothing(
                        index_elements=["tenant_id", "idempotency_key"]
                    ).returning(DurableQueueRecord.id)
                )
                inserted = result.scalar_one_or_none()
                if inserted is not None:
                    return True
                existing = await session.scalar(
                    select(DurableQueueRecord).where(
                        DurableQueueRecord.tenant_id == job.tenant_id,
                        DurableQueueRecord.idempotency_key == job.idempotency_key,
                    )
                )
                if existing is None or (
                    existing.id != job.job_id
                    or existing.kind != job.kind
                    or existing.payload_reference != job.payload_reference
                ):
                    raise QueueAdmissionError("idempotency key reused for a different job")
                return False
