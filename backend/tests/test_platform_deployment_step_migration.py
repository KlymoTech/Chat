"""Migration 0086 never invents completed infrastructure steps."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0086_platform_deployment_step_journal.py"


def migrate(connection, *, downgrade=False):
    spec = importlib.util.spec_from_file_location("northstar_0086_journal", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.op
    module.op = Operations(MigrationContext.configure(connection))
    try:
        if downgrade:
            module.downgrade()
        else:
            module.upgrade()
    finally:
        module.op = original


def test_step_journal_upgrade_has_no_historical_backfill_and_downgrade_requires_reconciliation():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE platform_deployment_leases (change_id CHAR(32) PRIMARY KEY)"
        ))
        change_id = "a" * 32
        conn.execute(text(
            "INSERT INTO platform_deployment_leases (change_id) VALUES (:id)"
        ), {"id": change_id})
        migrate(conn)
        assert conn.scalar(text("SELECT COUNT(*) FROM platform_deployment_steps")) == 0
        conn.execute(text(
            "INSERT INTO platform_deployment_steps "
            "(change_id, step_index, step_name, status, lease_token, started_at) "
            "VALUES (:id, 0, 'validate_dependencies', 'running', :token, CURRENT_TIMESTAMP)"
        ), {"id": change_id, "token": "b" * 32})
        with pytest.raises(RuntimeError, match="Reconcile"):
            migrate(conn, downgrade=True)
        assert conn.scalar(text("SELECT COUNT(*) FROM platform_deployment_steps")) == 1
        conn.execute(text("DELETE FROM platform_deployment_steps"))
        migrate(conn, downgrade=True)
        assert conn.scalar(text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='platform_deployment_steps'"
        )) == 0
