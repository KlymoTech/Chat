"""Disposable PostgreSQL acceptance for one-use signing authorizations."""
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

from northstar_api.modules.platform_runtime.queue_notification_signing_authorization_replay import (
    CommittedAuthorizationConsumption,
)


@pytest.mark.asyncio
async def test_authorization_consumption_concurrency_and_immutability(monkeypatch):
    dsn = os.getenv("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("disposable PostgreSQL not configured")
    parsed = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("refusing nonlocal PostgreSQL")
    dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "northstar_signing_auth_qa_" + uuid4().hex
    path = Path(__file__).resolve().parents[1] / (
        "migrations/versions/0096_signing_authorization_replay.py"
    )
    spec = importlib.util.spec_from_file_location("signing_auth_migration", path)
    assert spec is not None and spec.loader is not None
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
    worker = None
    created = False
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))  # noqa: S608
            created = True
        worker = create_async_engine(
            dsn, connect_args={"server_settings": {"search_path": f"{schema},public"}}
        )
        async with worker.begin() as conn:
            await conn.run_sync(upgrade)

        ledger = CommittedAuthorizationConsumption(
            async_sessionmaker(worker, expire_on_commit=False)
        )
        request = dict(
            authorization_id="authorization-once-12345678",
            release_id="release-12345678",
            run_id="jenkins-run-123456",
            now=datetime.now(UTC),
        )

        async def attempt():
            try:
                await ledger.consume(**request)
                return True
            except PermissionError:
                return False

        assert sorted(await asyncio.gather(attempt(), attempt())) == [False, True]
        for field, value in (
            ("authorization_id", "another-authorization-1234"),
            ("release_id", "release-87654321"),
            ("run_id", "jenkins-run-876543"),
        ):
            with pytest.raises(PermissionError):
                await ledger.consume(**{**request, field: value})

        for query in (
            "UPDATE platform_notification_signing_authorizations "
            "SET run_id = 'jenkins-run-999999'",
            "DELETE FROM platform_notification_signing_authorizations",
        ):
            with pytest.raises(DBAPIError):
                async with worker.begin() as conn:
                    await conn.execute(text(query))

        async with worker.connect() as conn:
            assert await conn.scalar(text(
                "SELECT count(*) FROM platform_notification_signing_authorizations"
            )) == 1
        with pytest.raises(RuntimeError, match="Cannot erase"):
            async with worker.begin() as conn:
                await conn.run_sync(downgrade)
    finally:
        if worker is not None:
            await worker.dispose()
        if created:
            async with admin.begin() as conn:
                await conn.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )  # noqa: S608
        await admin.dispose()
