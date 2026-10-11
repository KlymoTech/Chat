"""Execute revision 0079 against a disposable local PostgreSQL CI database.

This validates this additive migration, not the entire historical migration chain.
It refuses arbitrary deployment URLs and requires the dedicated CI opt-in flag.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "review-results" / "leads-migration"


async def review() -> None:
    if (
        os.environ.get("LEADS_MIGRATION_REVIEW") != "1"
        or os.environ.get("GITHUB_ACTIONS") != "true"
    ):
        raise RuntimeError("This check is restricted to its isolated GitHub CI service")
    engine = create_async_engine(
        "postgresql+asyncpg://postgres:ci-isolated-only@127.0.0.1:5544/leads_review"
    )
    module_path = ROOT / "backend/migrations/versions/0079_lead_workspace_operations.py"
    spec = importlib.util.spec_from_file_location("leads_migration", module_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    checks: list[str] = []
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        async with engine.begin() as connection:
            # Only the three referenced parent keys are required to exercise 0079.
            # Never drop or replace existing application tables in this test.
            for table in ("tenants", "workspaces", "leads"):
                await connection.execute(
                    text(f"CREATE TABLE {table} (id UUID PRIMARY KEY)")
                )
            await connection.execute(text("CREATE ROLE northstar_app NOLOGIN"))

            def migrate(sync_connection, operation: str) -> None:
                migration.op = Operations(MigrationContext.configure(sync_connection))
                getattr(migration, operation)()

            await connection.run_sync(migrate, "upgrade")
            checks.append("revision-0079-upgrade-on-postgresql")
            first, second = [uuid4() for _ in range(2)]
            for identifier in (first, second):
                for table in ("tenants", "workspaces", "leads"):
                    await connection.execute(
                        text(f"INSERT INTO {table} (id) VALUES (:id)"),
                        {"id": identifier},
                    )
                await connection.execute(
                    text(
                        "INSERT INTO lead_workspace_operations (lead_id,tenant_id,workspace_id,version,document) VALUES (:id,:id,:id,0,'{}'::jsonb)"
                    ),
                    {"id": identifier},
                )
            await connection.execute(text("SET LOCAL ROLE northstar_app"))
            await connection.execute(
                text("SELECT set_config('app.tenant_id', :id, true)"),
                {"id": str(first)},
            )
            assert list(
                await connection.scalars(
                    text("SELECT lead_id FROM lead_workspace_operations")
                )
            ) == [first]
            changed = await connection.execute(
                text(
                    "UPDATE lead_workspace_operations SET version=1 WHERE lead_id=:id"
                ),
                {"id": second},
            )
            assert changed.rowcount == 0
            checks.append("runtime-role-read-and-update-hide-other-tenant")
            try:
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "UPDATE lead_workspace_operations SET tenant_id=:other WHERE lead_id=:own"
                        ),
                        {"other": second, "own": first},
                    )
            except DBAPIError as error:
                assert getattr(error.orig, "sqlstate", None) == "42501", error
            else:
                raise AssertionError("RLS allowed moving a row to another tenant")
            checks.append("row-level-security-with-check-rejects-cross-tenant-write")
            await connection.execute(
                text("SELECT set_config('app.tenant_id', '', true)")
            )
            assert (
                list(
                    await connection.scalars(
                        text("SELECT lead_id FROM lead_workspace_operations")
                    )
                )
                == []
            )
            checks.append("missing-tenant-context-cannot-read-operations")
            await connection.execute(
                text("SELECT set_config('app.tenant_id', :id, true)"),
                {"id": str(second)},
            )
            assert list(
                await connection.scalars(
                    text("SELECT lead_id FROM lead_workspace_operations")
                )
            ) == [second]
            checks.append("second-tenant-sees-only-own-row")
            await connection.execute(text("RESET ROLE"))
            await connection.execute(
                text("DELETE FROM leads WHERE id=:id"), {"id": first}
            )
            assert list(
                await connection.scalars(
                    text("SELECT lead_id FROM lead_workspace_operations")
                )
            ) == [second]
            checks.append("lead-delete-cascades-operation-record")
            await connection.run_sync(migrate, "downgrade")
            assert (
                await connection.scalar(
                    text("SELECT to_regclass('public.lead_workspace_operations')")
                )
                is None
            )
            assert await connection.scalar(text("SELECT count(*) FROM tenants")) == 2
            checks.append("downgrade-removes-only-new-table")
            await connection.run_sync(migrate, "upgrade")
            assert (
                await connection.scalar(
                    text(
                        "SELECT relrowsecurity FROM pg_class WHERE relname='lead_workspace_operations'"
                    )
                )
                is True
            )
            checks.append("re-upgrade-restores-table-and-rls")
    finally:
        await engine.dispose()
        (OUT / "summary.json").write_text(
            json.dumps(
                {
                    "sourceSha": os.environ.get("GITHUB_SHA"),
                    "completedChecks": checks,
                    "passed": len(checks) == 8,
                },
                indent=2,
            )
        )
    print(json.dumps({"passed": True, "checks": checks}, indent=2))


if __name__ == "__main__":
    asyncio.run(review())
