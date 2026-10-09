"""Disposable PostgreSQL test: JUnit custody is unique and append-only."""
from __future__ import annotations

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
from sqlalchemy.ext.asyncio import create_async_engine

from northstar_api.modules.platform_runtime.queue_notification_jenkins_junit_custody_persistence import (
    NotificationJenkinsJunitCustodyRecord,
)

RELEASE = "release-123456"
RUN = "jenkins-build-123"
SUITES = ("notification_egress", "notification_secrets", "notification_worker")


def _fixture(release_id: str, run_id: str) -> dict:
    return {
        "release_id": release_id,
        "run_id": run_id,
        "branch": "feature/northstar-adaptive-architecture-20261008",
        "environment": "staging",
        "source_commit": "c" * 40,
        "source_digest": "a" * 64,
        "target_digest": "b" * 64,
        "witness_token": "signed.witness.token",
        "witness_sha256": "f" * 64,
        "index_bucket": "northstar-qualification-artifacts",
        "index_key": f"evidence/{release_id}/jenkins/{run_id}/junit/verified-index.json",
        "index_version_id": "locked-index-version-123",
        "index_sha256": "e" * 64,
        "suite_receipts": {
            suite: {
                "bucket": "northstar-qualification-artifacts",
                "key": f"evidence/{release_id}/jenkins/{run_id}/junit/{suite}.xml",
                "version_id": f"{suite}-version-1",
                "sha256": "d" * 64,
            }
            for suite in SUITES
        },
        "created_at": datetime.now(UTC),
    }


@pytest.mark.asyncio
async def test_append_only_junit_custody_and_release_run_uniqueness(monkeypatch):
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("no disposable PostgreSQL configured")
    parsed = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("refusing to mutate nonlocal PostgreSQL")
    dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "northstar_junit_custody_qa_" + uuid4().hex
    admin = create_async_engine(dsn)
    qualified = None
    created = False
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/0093_notification_jenkins_junit_custody.py"
    )
    spec = importlib.util.spec_from_file_location("northstar_junit_custody_migration", path)
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

    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))  # noqa: S608 - uuid-generated
            created = True
        qualified = create_async_engine(
            dsn,
            connect_args={"server_settings": {"search_path": f"{schema},public"}},
        )
        async with qualified.begin() as conn:
            await conn.run_sync(upgrade)
            await conn.execute(
                NotificationJenkinsJunitCustodyRecord.__table__.insert().values(
                    **_fixture(RELEASE, RUN)
                )
            )

        # The schema must independently stop both a second release for the
        # same run and a second run using the already certified release ID.
        for release, run in (
            ("release-unique999", RUN),
            (RELEASE, "jenkins-other999"),
        ):
            with pytest.raises(DBAPIError):
                async with qualified.begin() as conn:
                    await conn.execute(
                        NotificationJenkinsJunitCustodyRecord.__table__.insert().values(
                            **_fixture(release, run)
                        )
                    )

        for statement in (
            "UPDATE platform_notification_jenkins_junit_custody "
            "SET index_version_id = 'replacement' WHERE release_id = :release",
            "DELETE FROM platform_notification_jenkins_junit_custody "
            "WHERE release_id = :release",
        ):
            with pytest.raises(DBAPIError):
                async with qualified.begin() as conn:
                    await conn.execute(text(statement), {"release": RELEASE})

        # A downgrade must not silently erase already archived receipts.
        with pytest.raises(RuntimeError, match="Reconcile archived"):
            async with qualified.begin() as conn:
                await conn.run_sync(downgrade)

        async with qualified.connect() as conn:
            actual = await conn.scalar(text(
                "SELECT index_version_id FROM platform_notification_jenkins_junit_custody "
                "WHERE release_id = :release"
            ), {"release": RELEASE})
            assert actual == "locked-index-version-123"
    finally:
        if qualified is not None:
            await qualified.dispose()
        if created:
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))  # noqa: S608 - uuid-generated
        await admin.dispose()


def test_preceding_release_link_migration_plpgsql_delimiters_are_valid():
    previous = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/0092_notification_qualification_release_links.py"
    ).read_text(encoding="utf-8")
    assert "RETURNS trigger LANGUAGE plpgsql AS $$" in previous
    assert "END;\n        $$" in previous
