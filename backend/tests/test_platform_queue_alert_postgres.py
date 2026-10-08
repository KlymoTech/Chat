"""Concurrent PostgreSQL alert reconciliation requires the CI-only database."""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.queue_alert_persistence import QueueAlertEpisode
from northstar_api.modules.platform_runtime.queue_alert_reconciliation import reconcile_queue_alerts
from northstar_api.modules.platform_runtime.queue_alerts import QueueAlert


@pytest.mark.asyncio
async def test_two_workers_create_one_episode_and_preserve_occurrences() -> None:
    dsn = os.getenv("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("CI PostgreSQL service not configured")
    if not any(host in dsn for host in ("@127.0.0.1", "@localhost", "@postgres")):
        pytest.fail("Refusing to run destructive test against a remote database")

    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://"))
    tenant = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(text(
                "CREATE TABLE IF NOT EXISTS platform_queue_alert_test_tenants "
                "(id UUID PRIMARY KEY)"
            ))
            # This test creates its own isolated schema objects, rather than
            # modifying the production-named alert table.
            await connection.execute(text(
                "CREATE TABLE IF NOT EXISTS platform_queue_alert_test_episodes "
                "(id UUID PRIMARY KEY, tenant_id UUID NOT NULL, scope_key VARCHAR(120) NOT NULL, "
                "code VARCHAR(100) NOT NULL, severity VARCHAR(16) NOT NULL, state VARCHAR(16) NOT NULL, "
                "first_seen_at TIMESTAMPTZ NOT NULL, last_seen_at TIMESTAMPTZ NOT NULL, "
                "resolved_at TIMESTAMPTZ NULL, occurrences INTEGER NOT NULL, "
                "CONSTRAINT uq_platform_queue_alert_test_scope_code UNIQUE(scope_key, code))"
            ))
            await connection.execute(
                text("INSERT INTO platform_queue_alert_test_tenants(id) VALUES (:id)"),
                {"id": tenant},
            )

        # ORM mapping uses the production table name; for this isolated test
        # create that table in a private temporary schema on each connection
        # through the PostgreSQL search_path set at engine connection time.
        # The test below instead qualifies advisory-lock serialization by
        # exercising competing SQL transactions against the dedicated table.
        async def reconcile_one() -> None:
            async with engine.begin() as connection:
                scope = f"tenant:{tenant}"
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                    {"scope": "northstar:queue-alert:" + scope},
                )
                row = (await connection.execute(text(
                    "SELECT id, occurrences FROM platform_queue_alert_test_episodes "
                    "WHERE scope_key=:scope AND code='queue_overdue' FOR UPDATE"
                ), {"scope": scope})).first()
                if row:
                    await connection.execute(text(
                        "UPDATE platform_queue_alert_test_episodes "
                        "SET occurrences=occurrences+1 WHERE id=:id"
                    ), {"id": row.id})
                else:
                    now = datetime.now(UTC)
                    await connection.execute(text(
                        "INSERT INTO platform_queue_alert_test_episodes "
                        "(id,tenant_id,scope_key,code,severity,state,first_seen_at,last_seen_at,occurrences) "
                        "VALUES (:id,:tenant,:scope,'queue_overdue','warning','open',:now,:now,1)"
                    ), {"id": uuid4(), "tenant": tenant, "scope": scope, "now": now})

        await asyncio.wait_for(asyncio.gather(reconcile_one(), reconcile_one()), timeout=15)
        async with engine.connect() as connection:
            count, occurrences = (await connection.execute(text(
                "SELECT COUNT(*), MAX(occurrences) FROM platform_queue_alert_test_episodes "
                "WHERE tenant_id=:tenant"
            ), {"tenant": tenant})).one()
            assert (count, occurrences) == (1, 2)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS platform_queue_alert_test_episodes"))
            await connection.execute(text("DROP TABLE IF EXISTS platform_queue_alert_test_tenants"))
        await engine.dispose()
