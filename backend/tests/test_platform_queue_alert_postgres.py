"""Exercise real alert reconciliation concurrently on an isolated PostgreSQL schema."""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.queue_alert_reconciliation import reconcile_queue_alerts
from northstar_api.modules.platform_runtime.queue_alerts import QueueAlert


@pytest.mark.asyncio
async def test_concurrent_workers_open_only_one_alert_episode() -> None:
    dsn = os.getenv("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("disposable CI PostgreSQL service is not configured")
    if not any(host in dsn for host in ("@127.0.0.1", "@localhost", "@postgres")):
        pytest.fail("refusing to use a remote/shared database")

    schema = "queue_alert_qa_" + uuid4().hex
    base_url = dsn.replace("postgresql://", "postgresql+asyncpg://")
    admin = create_async_engine(base_url)
    engine = None
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            base_url, connect_args={"server_settings": {"search_path": f"{schema},public"}},
        )
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE platform_queue_alert_episodes ("
                "id UUID PRIMARY KEY, tenant_id UUID NOT NULL, scope_key VARCHAR(120) NOT NULL, "
                "code VARCHAR(100) NOT NULL, severity VARCHAR(16) NOT NULL, state VARCHAR(16) NOT NULL, "
                "first_seen_at TIMESTAMPTZ NOT NULL, last_seen_at TIMESTAMPTZ NOT NULL, "
                "resolved_at TIMESTAMPTZ, occurrences INTEGER NOT NULL, "
                "CONSTRAINT uq_platform_queue_alert_episode_scope_code UNIQUE(scope_key,code))"
            ))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        tenant = uuid4()
        alert = QueueAlert("queue_overdue", "warning", "tenant", 7, "threshold_exceeded")

        async def worker() -> dict[str, int]:
            async with sessions() as session, session.begin():
                return await reconcile_queue_alerts(session, tenant_id=tenant, alerts=(alert,))

        results = await asyncio.wait_for(asyncio.gather(worker(), worker()), timeout=15)
        assert sum(r["opened"] for r in results) == 1
        assert sum(r["updated"] for r in results) == 1
        async with engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT COUNT(*), MAX(occurrences) FROM platform_queue_alert_episodes "
                "WHERE tenant_id=:tenant"
            ), {"tenant": tenant})).one()
            assert tuple(row) == (1, 2)
    finally:
        if engine is not None:
            await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
