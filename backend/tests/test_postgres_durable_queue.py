"""Persistence tests for the idempotent durable queue adapter."""
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.postgres_queue import PostgresDurableJobStore
from northstar_api.modules.platform_runtime.queue_contract import DurableJob, QueueAdmissionError
from northstar_api.modules.platform_runtime.queue_persistence import DurableQueueRecord


@pytest.mark.asyncio
async def test_admission_is_committed_and_idempotent(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/queue.db")
    # Use the same referential contract as production with an isolated tenant table.
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.exec_driver_sql("CREATE TABLE tenants (id CHAR(32) PRIMARY KEY)")
        await conn.run_sync(DurableQueueRecord.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id, job_id = uuid4(), uuid4()
    async with engine.begin() as conn:
        await conn.exec_driver_sql("INSERT INTO tenants(id) VALUES (?)", (tenant_id.hex,))
    store = PostgresDurableJobStore(factory)
    job = DurableJob(job_id, tenant_id, "knowledge.index", "db:source:1", "request-0001")
    try:
        assert await store.accept(job) is True
        assert await store.accept(job) is False
        with pytest.raises(QueueAdmissionError, match="reused"):
            await store.accept(
                DurableJob(uuid4(), tenant_id, "knowledge.index", "db:source:2", "request-0001")
            )
        async with factory() as session:
            from sqlalchemy import select
            rows = (await session.scalars(select(DurableQueueRecord))).all()
            assert len(rows) == 1
            assert rows[0].status == "queued"
    finally:
        await engine.dispose()
