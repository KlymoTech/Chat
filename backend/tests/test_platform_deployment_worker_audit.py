"""Disposable SQLite coverage for append-only deployment worker audit sequencing.

PostgreSQL row-lock contention and append-only trigger behavior are separate
qualification gates; SQLite proves event chaining and fail-closed semantics.
"""
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.deployment_machine_identity import (
    DeploymentMachinePrincipal,
)
from northstar_api.modules.platform_runtime.deployment_worker_audit import (
    DeploymentAuditBlocked,
    DeploymentWorkerAuditTrail,
    validate_worker_audit_chain,
)
from northstar_api.modules.platform_runtime.deployment_worker_audit_persistence import (
    PlatformDeploymentWorkerAudit,
)


@pytest_asyncio.fixture
async def audit_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    change_id = uuid4()
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE platform_changes (id CHAR(32) PRIMARY KEY, "
            "environment VARCHAR(32) NOT NULL)"
        ))
        await conn.execute(text(
            "INSERT INTO platform_changes VALUES (:id, 'qualification')"
        ), {"id": change_id.hex})
        await conn.run_sync(PlatformDeploymentWorkerAudit.__table__.create)
    try:
        yield (
            DeploymentWorkerAuditTrail(async_sessionmaker(engine, expire_on_commit=False)),
            engine, change_id,
        )
    finally:
        await engine.dispose()


def principal(environment="qualification"):
    return DeploymentMachinePrincipal(
        subject="role/deployment-executor", environment=environment,
        token_id="private-opaque-token-id", scopes=frozenset(),
    )


async def events(engine, change_id):
    async with async_sessionmaker(engine)() as session:
        return list((await session.scalars(
            select(PlatformDeploymentWorkerAudit)
            .where(PlatformDeploymentWorkerAudit.change_id == change_id)
            .order_by(PlatformDeploymentWorkerAudit.sequence)
        )).all())


@pytest.mark.asyncio
async def test_intent_outcome_are_append_only_and_chain_linked(audit_database):
    audit, engine, change_id = audit_database
    first = await audit.begin(principal=principal(), change_id=change_id, action="claim")
    stored = await events(engine, change_id)
    assert len(stored) == 1
    assert stored[0].kind == "intent"
    assert "private-opaque-token-id" not in str(stored[0].__dict__)
    with pytest.raises(DeploymentAuditBlocked, match="reconciliation"):
        await audit.begin(principal=principal(), change_id=change_id, action="renew")
    await audit.finish(first, outcome="accepted")
    second = await audit.begin(principal=principal(), change_id=change_id, action="renew")
    await audit.finish(second, outcome="rejected")
    stored = await events(engine, change_id)
    assert [event.sequence for event in stored] == [1, 2, 3, 4]
    assert validate_worker_audit_chain(stored)
    assert stored[1].previous_digest == stored[0].event_digest


@pytest.mark.asyncio
async def test_unknown_result_requires_manual_reconciliation(audit_database):
    audit, engine, change_id = audit_database
    attempt = await audit.begin(principal=principal(), change_id=change_id, action="begin",
                                step_index=0)
    await audit.finish(attempt, outcome="unknown")
    with pytest.raises(DeploymentAuditBlocked, match="reconciliation"):
        await audit.begin(principal=principal(), change_id=change_id, action="verify",
                          step_index=0)
    assert len(await events(engine, change_id)) == 2


@pytest.mark.asyncio
async def test_wrong_environment_denied_without_audit_row(audit_database):
    audit, engine, change_id = audit_database
    with pytest.raises(DeploymentAuditBlocked, match="environment"):
        await audit.begin(principal=principal("production"), change_id=change_id, action="claim")
    assert not await events(engine, change_id)


@pytest.mark.asyncio
async def test_duplicate_completion_and_missing_intent_denied(audit_database):
    audit, engine, change_id = audit_database
    attempt = await audit.begin(principal=principal(), change_id=change_id, action="claim")
    with pytest.raises(ValueError, match="invalid audit outcome"):
        await audit.finish(attempt, outcome="completed")
    await audit.finish(attempt, outcome="accepted")
    with pytest.raises(DeploymentAuditBlocked, match="missing or superseded"):
        await audit.finish(attempt, outcome="accepted")
    assert len(await events(engine, change_id)) == 2


@pytest.mark.asyncio
async def test_tampered_event_detected_by_chain_verifier(audit_database):
    audit, engine, change_id = audit_database
    attempt = await audit.begin(principal=principal(), change_id=change_id, action="claim")
    await audit.finish(attempt, outcome="accepted")
    stored = await events(engine, change_id)
    stored[0].machine_subject = "role/intruder"
    assert not validate_worker_audit_chain(stored)
    stored[0].machine_subject = "role/deployment-executor"
    stored[1].previous_digest = "f" * 64
    assert not validate_worker_audit_chain(stored)
