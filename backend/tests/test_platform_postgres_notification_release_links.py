"""Live disposable PostgreSQL qualification: release link is immutable and required."""
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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.queue_notification_qualification_governance import (
    QualificationGovernanceConflict,
    change_qualification_status,
)
from northstar_api.modules.platform_runtime.queue_notification_qualification_persistence import (
    NotificationWorkerQualificationRecord,
)
from northstar_api.modules.platform_runtime.queue_notification_qualification_store import (
    PostgresNotificationQualificationStore,
)
from northstar_api.modules.platform_runtime.queue_notification_release_link_persistence import (
    NotificationQualificationReleaseLink,
)


@pytest.mark.asyncio
async def test_postgres_release_link_gates_approval_and_blocks_mutations(monkeypatch):
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("local disposable PostgreSQL unavailable")
    parsed = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("refusing to mutate a nonlocal PostgreSQL database")
    dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "northstar_release_link_qa_" + uuid4().hex
    admin = create_async_engine(dsn)
    engine = None
    created = False
    module_path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/0092_notification_qualification_release_links.py"
    )
    spec = importlib.util.spec_from_file_location("notification_release_link_migration", module_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def upgrade(connection):
        context = MigrationContext.configure(connection)
        monkeypatch.setattr(migration, "op", Operations(context))
        migration.upgrade()

    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        engine = create_async_engine(
            dsn, connect_args={"server_settings": {"search_path": f"{schema},public"}},
        )
        async with engine.begin() as connection:
            await connection.run_sync(NotificationWorkerQualificationRecord.__table__.create)
            await connection.run_sync(upgrade)
            await connection.execute(NotificationWorkerQualificationRecord.__table__.insert().values(
                id="jenkins:jenkins-build-123", environment="staging",
                source_digest="a" * 64, target_digest="b" * 64,
                proof_tokens=["signed1", "signed2", "signed3"],
                approved=False, revoked=False, revision=1,
                issued_by="jenkins:independent-runner", created_at=datetime.now(UTC),
            ))
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def noop_audit(_session, _data):
            return None

        # A passing Jenkins run without a linked release must not be approved.
        with pytest.raises(QualificationGovernanceConflict):
            async with sessions.begin() as session:
                await change_qualification_status(
                    session, qualification_id="jenkins:jenkins-build-123",
                    expected_revision=1, actor_id="independent-reviewer",
                    authorized=True, action="approve", audit=noop_audit,
                )

        async with engine.begin() as connection:
            await connection.execute(NotificationQualificationReleaseLink.__table__.insert().values(
                qualification_id="jenkins:jenkins-build-123",
                release_id="release-123456", run_id="jenkins-build-123",
                environment="staging", source_commit="c" * 40,
                image_digest="sha256:" + "d" * 64,
                source_digest="a" * 64, target_digest="b" * 64,
                signed_manifest_sha256="e" * 64,
                manifest_bucket="northstar-qualification-evidence",
                manifest_key="evidence/release-123456/release-manifest.json",
                manifest_version_id="manifest-v1",
                manifest_object_sha256="f" * 64,
                attestation_bucket="northstar-qualification-evidence",
                attestation_key="evidence/release-123456/jenkins/jenkins-build-123/certification-attestation.token",
                attestation_version_id="attestation-v1",
                attestation_sha256="1" * 64,
                created_at=datetime.now(UTC),
            ))
        async with sessions.begin() as session:
            assert await change_qualification_status(
                session, qualification_id="jenkins:jenkins-build-123",
                expected_revision=1, actor_id="independent-reviewer",
                authorized=True, action="approve", audit=noop_audit,
            ) == 2
        evidence = await PostgresNotificationQualificationStore(sessions).read(
            "jenkins:jenkins-build-123"
        )
        assert evidence is not None and evidence.approved is True

        for command in (
            "UPDATE platform_notification_qualification_release_links SET release_id = 'altered-release' "
            "WHERE qualification_id = 'jenkins:jenkins-build-123'",
            "DELETE FROM platform_notification_qualification_release_links "
            "WHERE qualification_id = 'jenkins:jenkins-build-123'",
        ):
            with pytest.raises(DBAPIError):
                async with engine.begin() as connection:
                    await connection.execute(text(command))
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
