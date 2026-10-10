"""Disposable PostgreSQL audit qualification: serialization and immutable triggers."""
from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
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

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions"
    / "0087_platform_deployment_worker_audit.py"
)


def _upgrade(connection):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    spec = importlib.util.spec_from_file_location("northstar_pg_0087_audit", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = module.op
    module.op = Operations(MigrationContext.configure(connection))
    try:
        module.upgrade()
    finally:
        module.op = old


@pytest.mark.asyncio
async def test_competing_workers_cannot_bypass_audit_or_edit_history():
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("disposable PostgreSQL qualification service is unavailable")
    if not any(host in dsn for host in ("@localhost", "@127.0.0.1", "@postgres")):
        pytest.fail("refusing to mutate a shared/nonlocal PostgreSQL database")

    schema = "northstar_audit_qa_" + uuid4().hex
    base_url = dsn.replace("postgresql://", "postgresql+asyncpg://")
    admin = create_async_engine(base_url)
    isolated = None
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = create_async_engine(
            base_url,
            connect_args={"server_settings": {"search_path": f"{schema},public"}},
        )
        change_id = uuid4()
        async with isolated.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE platform_changes (id UUID PRIMARY KEY, "
                "environment VARCHAR(32) NOT NULL)"
            ))
            await conn.execute(text(
                "INSERT INTO platform_changes (id, environment) "
                "VALUES (:id, 'qualification')"
            ), {"id": change_id})
            await conn.run_sync(_upgrade)

        sessions = async_sessionmaker(isolated, expire_on_commit=False)
        audit = DeploymentWorkerAuditTrail(sessions)
        machine = DeploymentMachinePrincipal(
            subject="role/deployment-executor", environment="qualification",
            token_id=uuid4().hex, scopes=frozenset(),
        )

        async def contender():
            try:
                return await audit.begin(
                    principal=machine, change_id=change_id, action="claim"
                )
            except DeploymentAuditBlocked:
                return None

        results = await asyncio.wait_for(
            asyncio.gather(contender(), contender()), timeout=15,
        )
        winners = [result for result in results if result is not None]
        assert len(winners) == 1
        await audit.finish(winners[0], outcome="rejected")
        async with sessions() as session:
            rows = list((await session.scalars(
                select(PlatformDeploymentWorkerAudit)
                .where(PlatformDeploymentWorkerAudit.change_id == change_id)
                .order_by(PlatformDeploymentWorkerAudit.sequence)
            )).all())
        assert len(rows) == 2
        assert validate_worker_audit_chain(rows)

        # Independent SQL UPDATE and DELETE are blocked by migration trigger.
        for mutation in (
            "UPDATE platform_deployment_worker_audit SET action='forged'",
            "DELETE FROM platform_deployment_worker_audit",
        ):
            with pytest.raises(Exception, match="append-only"):
                async with isolated.begin() as conn:
                    await conn.execute(text(mutation))
    finally:
        if isolated is not None:
            await isolated.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
