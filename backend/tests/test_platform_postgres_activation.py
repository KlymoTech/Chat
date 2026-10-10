"""PostgreSQL qualification for the single-active configuration migration.

Runs only with PLATFORM_TEST_POSTGRES_DSN; CI supplies a disposable database.
Never connect this suite to shared, staging, or production databases.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path

import asyncpg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0079_platform_single_active_config.py"
INDEX = "uq_platform_config_versions_one_active_per_environment"


def _upgrade(sync_connection) -> None:
    spec = importlib.util.spec_from_file_location("test_platform_migration_0079_pg", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    operations = Operations(MigrationContext.configure(sync_connection))
    previous = module.op
    module.op = operations
    try:
        module.upgrade()
    finally:
        module.op = previous


def _test_dsn() -> str:
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PLATFORM_TEST_POSTGRES_DSN is not configured")
    # Prevent accidental use against arbitrary external database endpoints.
    if not any(host in dsn for host in ("@localhost", "@127.0.0.1", "@postgres")):
        pytest.fail("PostgreSQL test DSN must target a local/disposable CI service")
    return dsn


async def _prepare(connection: asyncpg.Connection) -> None:
    await connection.execute("DROP TABLE IF EXISTS platform_config_versions")
    await connection.execute(
        "CREATE TABLE platform_config_versions (id TEXT PRIMARY KEY, "
        "environment TEXT NOT NULL, active BOOLEAN NOT NULL)"
    )


async def test_pg_migration_preserves_duplicate_records_and_blocks_upgrade() -> None:
    dsn = _test_dsn()
    connection = await asyncpg.connect(dsn)
    try:
        await _prepare(connection)
        await connection.execute(
            "INSERT INTO platform_config_versions VALUES "
            "('first', 'production', true), ('second', 'production', true)"
        )
        engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://"))
        try:
            with pytest.raises(RuntimeError, match="Multiple active"):
                async with engine.begin() as transaction:
                    await transaction.run_sync(_upgrade)
        finally:
            await engine.dispose()
        assert await connection.fetchval("SELECT COUNT(*) FROM platform_config_versions") == 2
        assert not await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = $1)", INDEX
        )
    finally:
        await connection.execute("DROP TABLE IF EXISTS platform_config_versions")
        await connection.close()


async def test_pg_competing_promotions_preserve_single_active_revision() -> None:
    dsn = _test_dsn()
    admin = await asyncpg.connect(dsn)
    try:
        await _prepare(admin)
        await admin.execute(
            "INSERT INTO platform_config_versions VALUES "
            "('old', 'production', true), ('next_a', 'production', false), "
            "('next_b', 'production', false)"
        )
        engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://"))
        try:
            async with engine.begin() as connection:
                await connection.run_sync(_upgrade)
        finally:
            await engine.dispose()

        async def promote(target: str) -> str:
            connection = await asyncpg.connect(dsn)
            try:
                async with connection.transaction():
                    # Both competitors must retire the same source revision.
                    retired = await connection.execute(
                        "UPDATE platform_config_versions SET active=false "
                        "WHERE id='old' AND active=true"
                    )
                    if retired != "UPDATE 1":
                        return "stale"
                    await connection.execute(
                        "UPDATE platform_config_versions SET active=true WHERE id=$1 AND active=false",
                        target,
                    )
                    return "promoted"
            finally:
                await connection.close()

        results = await asyncio.wait_for(
            asyncio.gather(promote("next_a"), promote("next_b")), timeout=15
        )
        assert sorted(results) == ["promoted", "stale"]
        assert await admin.fetchval(
            "SELECT COUNT(*) FROM platform_config_versions "
            "WHERE environment='production' AND active=true"
        ) == 1
    finally:
        await admin.execute("DROP TABLE IF EXISTS platform_config_versions")
        await admin.close()
