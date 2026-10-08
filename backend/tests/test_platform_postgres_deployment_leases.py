"""PostgreSQL CAS qualification for deployment worker leases.

Run only against the disposable local PostgreSQL CI service. Never use a shared
database: this suite creates and drops isolated platform test tables.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.deployment_leases import DeploymentLeaseService

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0085_platform_deployment_leases.py"


def _upgrade(sync_connection):
    spec = importlib.util.spec_from_file_location("northstar_pg_0085", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = module.op
    module.op = Operations(MigrationContext.configure(sync_connection))
    try:
        module.upgrade()
    finally:
        module.op = previous


def _dsn():
    value = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not value:
        pytest.skip("PLATFORM_TEST_POSTGRES_DSN is not configured")
    if not any(host in value for host in ("@localhost", "@127.0.0.1", "@postgres")):
        pytest.fail("Only a disposable local PostgreSQL test service is permitted")
    return value


@pytest.mark.asyncio
async def test_competing_deployment_workers_are_fenced():
    dsn = _dsn()
    admin = await asyncpg.connect(dsn)
    engine = None
    try:
        await admin.execute("DROP TABLE IF EXISTS platform_deployment_leases")
        await admin.execute("DROP TABLE IF EXISTS platform_config_versions")
        await admin.execute("DROP TABLE IF EXISTS platform_changes")
        await admin.execute(
            "CREATE TABLE platform_changes ("
            "id UUID PRIMARY KEY, environment VARCHAR(32) NOT NULL, "
            "status VARCHAR(32) NOT NULL, requested_by UUID NOT NULL, "
            "approved_by UUID, action VARCHAR(16) NOT NULL, "
            "source_digest VARCHAR(64) NOT NULL, target_digest VARCHAR(64) NOT NULL)"
        )
        await admin.execute(
            "CREATE TABLE platform_config_versions ("
            "id UUID PRIMARY KEY, environment VARCHAR(32) NOT NULL, "
            "active BOOLEAN NOT NULL, digest VARCHAR(64) NOT NULL)"
        )
        change_id, requester, approver = uuid4(), uuid4(), uuid4()
        source, target = "a" * 64, "b" * 64
        await admin.execute(
            "INSERT INTO platform_changes VALUES ($1, 'production', 'approved', $2, $3, "
            "'migrate', $4, $5)", change_id, requester, approver, source, target,
        )
        await admin.execute(
            "INSERT INTO platform_config_versions VALUES "
            "($1, 'production', true, $2), ($3, 'production', false, $4)",
            uuid4(), source, uuid4(), target,
        )
        engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://"))
        async with engine.begin() as connection:
            await connection.run_sync(_upgrade)
            await connection.exec_driver_sql(
                "INSERT INTO platform_deployment_leases "
                "(change_id, environment, source_digest, target_digest, status) "
                "VALUES ($1, 'production', $2, $3, 'ready')",
                (change_id, source, target),
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        worker = DeploymentLeaseService(factory)
        outcomes = await asyncio.wait_for(asyncio.gather(
            worker.claim(change_id, owner="worker-a"),
            worker.claim(change_id, owner="worker-b"),
        ), timeout=15)
        winners = [claim for claim in outcomes if claim is not None]
        assert len(winners) == 1
        winner = winners[0]
        assert await worker.renew(winner)
        assert not await worker.close(winner)  # cannot finish before control-plane completion
        await admin.execute("UPDATE platform_changes SET status='completed' WHERE id=$1", change_id)
        assert await worker.close(winner)
        assert await worker.claim(change_id, owner="worker-c") is None
        assert await admin.fetchval(
            "SELECT status FROM platform_deployment_leases WHERE change_id=$1", change_id
        ) == "closed"
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.execute("DROP TABLE IF EXISTS platform_deployment_leases")
        await admin.execute("DROP TABLE IF EXISTS platform_config_versions")
        await admin.execute("DROP TABLE IF EXISTS platform_changes")
        await admin.close()
