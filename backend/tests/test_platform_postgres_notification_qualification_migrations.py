"""Exercise qualification migrations 0090/0091 on disposable PostgreSQL only."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def load(filename: str):
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), VERSIONS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_qualification_migrations_upgrade_constraints_and_safe_downgrade(monkeypatch):
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("disposable PostgreSQL service not configured")
    url = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if url.hostname not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("refusing to modify nonlocal database")
    engine = create_async_engine(dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    schema = "northstar_qualification_migration_" + uuid4().hex
    m90 = load("0090_platform_notification_worker_qualification.py")
    m91 = load("0091_notification_qualification_governance.py")
    created = False

    def migrate(connection, fn, module):
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        ctx = MigrationContext.configure(connection)
        monkeypatch.setattr(module, "op", Operations(ctx))
        fn()

    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        async with engine.begin() as conn:
            await conn.run_sync(migrate, m90.upgrade, m90)
            await conn.run_sync(migrate, m91.upgrade, m91)
        async with engine.begin() as conn:
            await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            columns = await conn.run_sync(
                lambda connection: {c["name"] for c in inspect(connection).get_columns(
                    "platform_notification_worker_qualifications", schema=schema
                )}
            )
            assert {"revision", "issued_by", "approved_by", "revoked_by"} <= columns
            await conn.execute(text(
                "INSERT INTO platform_notification_worker_qualifications "
                "(id, environment, source_digest, target_digest, proof_tokens, "
                "approved, revoked, issued_by, approved_by, created_at) "
                "VALUES ('legacy-test', 'staging', :src, :tgt, '[]'::json, "
                "false, false, 'pipeline', 'reviewer', now())"
            ), {"src": "a" * 64, "tgt": "b" * 64})
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await conn.execute(text(
                    "UPDATE platform_notification_worker_qualifications "
                    "SET approved_by = 'pipeline' WHERE id = 'legacy-test'"
                ))
        with pytest.raises(RuntimeError, match="Reconcile"):
            async with engine.begin() as conn:
                await conn.run_sync(migrate, m91.downgrade, m91)
        async with engine.begin() as conn:
            await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await conn.execute(text("DELETE FROM platform_notification_worker_qualifications"))
            await conn.run_sync(migrate, m91.downgrade, m91)
            await conn.run_sync(migrate, m90.downgrade, m90)
    finally:
        if created:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
