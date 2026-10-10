"""Disposable PostgreSQL: signing claims are unique, immutable and race-safe."""
from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.queue_notification_custody_signing_claims import (
    CommittedPostgresSigningClaims,
)

pytestmark = pytest.mark.asyncio


async def test_signing_claims_are_unique_immutable_and_concurrent(monkeypatch):
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("disposable PostgreSQL not configured")
    parsed = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("refusing nonlocal PostgreSQL")
    dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "northstar_signing_claim_qa_" + uuid4().hex
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/0095_notification_custody_signing_claims.py"
    )
    spec = importlib.util.spec_from_file_location("custody_claim_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def upgrade(connection):
        context = MigrationContext.configure(connection)
        monkeypatch.setattr(migration, "op", Operations(context))
        migration.upgrade()

    def downgrade(connection):
        context = MigrationContext.configure(connection)
        monkeypatch.setattr(migration, "op", Operations(context))
        migration.downgrade()

    admin = create_async_engine(dsn)
    engine = None
    created = False
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))  # noqa: S608 - generated UUID
            created = True
        engine = create_async_engine(
            dsn,
            connect_args={"server_settings": {"search_path": f"{schema},public"}},
        )
        async with engine.begin() as conn:
            await conn.run_sync(upgrade)

        claims = CommittedPostgresSigningClaims(
            async_sessionmaker(engine, expire_on_commit=False)
        )
        now = datetime.now(UTC)
        request = {
            "release_id": "release-12345678",
            "run_id": "run-12345678",
            "witness_sha256": "a" * 64,
            "now": now,
        }
        async def submit():
            try:
                await claims.claim(**request)
                return True
            except PermissionError:
                return False

        results = await asyncio.gather(submit(), submit())
        assert sorted(results) == [False, True]
        async with engine.connect() as conn:
            assert await conn.scalar(text(
                "SELECT count(*) FROM platform_notification_custody_signing_claims"
            )) == 1

        for column, changed in (
            ("release_id", "release-87654321"),
            ("run_id", "run-87654321"),
            ("witness_sha256", "b" * 64),
        ):
            modified = {**request, column: changed}
            with pytest.raises(PermissionError):
                await claims.claim(**modified)

        for statement in (
            "UPDATE platform_notification_custody_signing_claims "
            "SET run_id='run-99999999'",
            "DELETE FROM platform_notification_custody_signing_claims",
        ):
            with pytest.raises(DBAPIError):
                async with engine.begin() as conn:
                    await conn.execute(text(statement))

        with pytest.raises(RuntimeError, match="Cannot destroy"):
            async with engine.begin() as conn:
                await conn.run_sync(downgrade)
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            async with admin.begin() as conn:
                await conn.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )  # noqa: S608 - generated UUID
        await admin.dispose()
