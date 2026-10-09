"""Qualify an actual non-superuser PostgreSQL worker login in disposable CI.

Do not run against production databases. All role/schema names are randomized
and all infrastructure lives only in the local disposable PostgreSQL service.
"""
from __future__ import annotations

import os
from importlib import util
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.deployment_machine_identity import (
    DeploymentMachinePrincipal,
)
from northstar_api.modules.platform_runtime.deployment_worker_audit import (
    DeploymentWorkerAuditTrail,
)
from northstar_api.modules.platform_runtime.deployment_worker_audit_persistence import (
    PlatformDeploymentWorkerAudit,
)
from northstar_api.modules.platform_runtime.deployment_worker_database import (
    WorkerDatabaseSecurityError,
    verify_worker_database_identity,
)


def _disposable_dsn() -> str:
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Disposable PostgreSQL is not available")
    if not any(part in dsn for part in ("@localhost", "@127.0.0.1", "@postgres")):
        pytest.fail("Refusing worker-role qualification on a non-local database")
    return dsn


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions"
    / "0087_platform_deployment_worker_audit.py"
)


@pytest.mark.asyncio
async def test_real_unprivileged_worker_role_can_audit_without_editing_approvals():
    dsn = _disposable_dsn()
    schema = "ns_workertest_" + uuid4().hex
    role = "ns_worker_" + uuid4().hex[:16]
    password = uuid4().hex + uuid4().hex
    admin = await asyncpg.connect(dsn)
    worker_engine = None
    created_role = False
    try:
        # Identifiers/password are generated safe alphanumerics, not external input.
        await admin.execute(f'CREATE ROLE "{role}" LOGIN PASSWORD \'{password}\'')
        created_role = True
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        await admin.execute(f"""
            CREATE TABLE "{schema}".platform_changes (
                id UUID PRIMARY KEY, environment VARCHAR(32) NOT NULL
            );
            CREATE TABLE "{schema}".platform_deployment_leases (id UUID PRIMARY KEY);
            CREATE TABLE "{schema}".platform_deployment_steps (id UUID PRIMARY KEY);
        """)
        # Use the same migration DDL as the application for the worker audit.
        spec = util.spec_from_file_location("ns_worker_audit_0087", MIGRATION_PATH)
        assert spec is not None and spec.loader is not None
        migration = util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        admin_engine = create_async_engine(
            make_url(dsn).set(drivername="postgresql+asyncpg").render_as_string(hide_password=False),
            connect_args={"server_settings": {"search_path": f"{schema},public"}},
        )
        try:
            async with admin_engine.begin() as conn:
                def run_upgrade(connection):
                    old = migration.op
                    migration.op = Operations(MigrationContext.configure(connection))
                    try:
                        migration.upgrade()
                    finally:
                        migration.op = old
                await conn.run_sync(run_upgrade)
        finally:
            await admin_engine.dispose()

        await admin.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        for table in ("platform_changes", "platform_deployment_leases", "platform_deployment_steps"):
            await admin.execute(f'GRANT SELECT ON "{schema}".{table} TO "{role}"')
        await admin.execute(f'GRANT UPDATE ON "{schema}".platform_deployment_leases TO "{role}"')
        await admin.execute(f'GRANT INSERT, UPDATE ON "{schema}".platform_deployment_steps TO "{role}"')
        await admin.execute(
            f'GRANT SELECT, INSERT ON "{schema}".platform_deployment_worker_audit TO "{role}"'
        )

        worker_url = make_url(dsn).set(
            drivername="postgresql+asyncpg", username=role, password=password
        ).render_as_string(hide_password=False)
        worker_engine = create_async_engine(
            worker_url, connect_args={"server_settings": {"search_path": f"{schema},public"}}
        )
        await verify_worker_database_identity(worker_engine, expected_role=role)

        audit = DeploymentWorkerAuditTrail(async_sessionmaker(worker_engine, expire_on_commit=False))
        change_id = uuid4()
        await admin.execute("SELECT set_config('search_path', $1, false)", f"{schema},public")
        await admin.execute(
            "INSERT INTO platform_changes (id, environment) VALUES ($1, $2)",
            change_id, "qualification",
        )
        actor = DeploymentMachinePrincipal(
            subject="role/qualified-worker", environment="qualification",
            token_id=uuid4().hex, scopes=frozenset(),
        )
        attempt = await audit.begin(
            principal=actor, change_id=change_id, action="claim",
        )
        await audit.finish(attempt, outcome="rejected")
        async with async_sessionmaker(worker_engine)() as session:
            events = (await session.scalars(
                select(PlatformDeploymentWorkerAudit)
                .where(PlatformDeploymentWorkerAudit.change_id == change_id)
            )).all()
            assert len(events) == 2

        # The worker must not obtain direct UPDATE on an approved change.
        async with worker_engine.connect() as conn:
            with pytest.raises(DBAPIError):
                await conn.execute(text(
                    "UPDATE platform_changes SET environment='production' WHERE id=:id"
                ), {"id": change_id})
            await conn.rollback()

        # An extra audit DELETE permission must invalidate startup.
        await admin.execute(f'GRANT DELETE ON "{schema}".platform_deployment_worker_audit TO "{role}"')
        with pytest.raises(WorkerDatabaseSecurityError, match="least-privilege"):
            await verify_worker_database_identity(worker_engine, expected_role=role)
    finally:
        if worker_engine is not None:
            await worker_engine.dispose()
        try:
            await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            if created_role:
                await admin.execute(f'DROP ROLE "{role}"')
            await admin.close()
