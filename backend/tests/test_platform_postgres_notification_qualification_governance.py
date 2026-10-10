"""Disposable PostgreSQL governance qualification: independent reviews and rollback.

Only runs against explicitly configured local CI PostgreSQL, in its own schema.
Approval/revocation never starts notification delivery.
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.queue_notification_qualification_governance import (
    QualificationGovernanceConflict,
    change_qualification_status,
)
from northstar_api.modules.platform_runtime.queue_notification_qualification_persistence import (
    NotificationWorkerQualificationRecord,
)


@pytest.mark.asyncio
async def test_postgres_qualification_approval_revocation_concurrency_and_rollback():
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("isolated PostgreSQL CI service is not configured")
    parsed = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("refusing to modify a nonlocal database")

    url = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "northstar_qualification_qa_" + uuid4().hex
    admin = create_async_engine(url)
    isolated = None
    created = False
    async def audit(_session, _details):
        # Production audit is owned by the caller and shares this transaction.
        return None

    async def decide(sessions, actor, action, revision):
        async with sessions() as session:
            async with session.begin():
                return await change_qualification_status(
                    session, qualification_id="certification-123",
                    expected_revision=revision, actor_id=actor,
                    authorized=True, action=action, audit=audit,
                )

    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        isolated = create_async_engine(
            url, connect_args={"server_settings": {"search_path": f"{schema},public"}}
        )
        async with isolated.begin() as conn:
            await conn.run_sync(NotificationWorkerQualificationRecord.__table__.create)
            await conn.execute(
                NotificationWorkerQualificationRecord.__table__.insert().values(
                    id="certification-123", environment="qualification",
                    source_digest="a" * 64, target_digest="b" * 64,
                    proof_tokens=["signed.proof"], approved=False, revoked=False,
                    revision=1, issued_by="pipeline-issuer",
                    created_at=datetime.now(UTC),
                )
            )
        sessions = async_sessionmaker(isolated, expire_on_commit=False)

        # The issuer cannot approve its own evidence, even with valid permission.
        with pytest.raises(QualificationGovernanceConflict):
            await decide(sessions, "pipeline-issuer", "approve", 1)
        outcomes = await asyncio.wait_for(
            asyncio.gather(
                decide(sessions, "reviewer-a", "approve", 1),
                decide(sessions, "reviewer-b", "approve", 1),
                return_exceptions=True,
            ),
            timeout=15,
        )
        assert len([x for x in outcomes if x == 2]) == 1
        assert len([x for x in outcomes if isinstance(x, QualificationGovernanceConflict)]) == 1
        async with sessions() as session:
            row = await session.get(NotificationWorkerQualificationRecord, "certification-123")
            assert row.approved and not row.revoked and row.revision == 2
            assert row.approved_by in {"reviewer-a", "reviewer-b"}

        # Stale revisions do not overwrite an approved record.
        with pytest.raises(QualificationGovernanceConflict):
            await decide(sessions, "reviewer-c", "revoke", 1)

        # Audit failure aborts both mutation and associated audit transaction.
        async def rejected_audit(_session, _details):
            raise RuntimeError("simulated audit persistence failure")

        with pytest.raises(RuntimeError):
            async with sessions() as session:
                async with session.begin():
                    await change_qualification_status(
                        session, qualification_id="certification-123",
                        expected_revision=2, actor_id="security-reviewer",
                        authorized=True, action="revoke", audit=rejected_audit,
                    )
        async with sessions() as session:
            row = await session.get(NotificationWorkerQualificationRecord, "certification-123")
            assert row.approved and not row.revoked and row.revision == 2

        assert await decide(sessions, "security-reviewer", "revoke", 2) == 3
        async with sessions() as session:
            row = await session.get(NotificationWorkerQualificationRecord, "certification-123")
            assert row.revoked and not row.approved and row.revision == 3
            assert row.revoked_by == "security-reviewer"
        with pytest.raises(QualificationGovernanceConflict):
            await decide(sessions, "reviewer-d", "approve", 3)
    finally:
        if isolated is not None:
            await isolated.dispose()
        if created:
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
