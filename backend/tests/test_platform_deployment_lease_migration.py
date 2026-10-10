"""Migration 0085: legacy approvals never acquire executable worker claims."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0085_platform_deployment_leases.py"


def _run(connection, *, downgrade=False):
    spec = importlib.util.spec_from_file_location("northstar_0085_leases", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = module.op
    module.op = Operations(MigrationContext.configure(connection))
    try:
        if downgrade:
            module.downgrade()
        else:
            module.upgrade()
    finally:
        module.op = old


def test_existing_approvals_are_not_backfilled_and_downgrade_is_guarded():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE platform_changes (id CHAR(32) PRIMARY KEY)"))
        change_id = "a" * 32
        conn.execute(text("INSERT INTO platform_changes (id) VALUES (:id)"), {"id": change_id})
        _run(conn)
        assert conn.scalar(text("SELECT COUNT(*) FROM platform_deployment_leases")) == 0
        conn.execute(text(
            "INSERT INTO platform_deployment_leases "
            "(change_id, environment, source_digest, target_digest, status) "
            "VALUES (:id, 'production', :source, :target, 'ready')"
        ), {"id": change_id, "source": "a" * 64, "target": "b" * 64})
        with pytest.raises(RuntimeError, match="Reconcile"):
            _run(conn, downgrade=True)
        assert conn.scalar(text("SELECT COUNT(*) FROM platform_deployment_leases")) == 1
        conn.execute(text("DELETE FROM platform_deployment_leases"))
        _run(conn, downgrade=True)
        assert not conn.scalar(text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='platform_deployment_leases'"
        ))
