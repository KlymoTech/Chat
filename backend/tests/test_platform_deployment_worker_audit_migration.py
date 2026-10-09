"""0087 audit migration adds no forged historical records and guards downgrades."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions"
    / "0087_platform_deployment_worker_audit.py"
)


def migrate(connection, *, downgrade=False):
    spec = importlib.util.spec_from_file_location("northstar_0087_audit", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = module.op
    module.op = Operations(MigrationContext.configure(connection))
    try:
        if downgrade:
            module.downgrade()
        else:
            module.upgrade()
    finally:
        module.op = previous


def test_audit_migration_has_no_backfill_and_downgrade_preserves_history():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE platform_changes (id CHAR(32) PRIMARY KEY, "
            "environment VARCHAR(32) NOT NULL)"
        ))
        change_id = uuid4().hex
        conn.execute(text(
            "INSERT INTO platform_changes VALUES (:id, 'qualification')"
        ), {"id": change_id})
        migrate(conn)
        assert conn.scalar(text("SELECT COUNT(*) FROM platform_deployment_worker_audit")) == 0
        conn.execute(text(
            "INSERT INTO platform_deployment_worker_audit "
            "(id, change_id, attempt_id, sequence, kind, action, environment, "
            "machine_subject, token_id_hash, occurred_at, previous_digest, event_digest) "
            "VALUES (:id, :change, :attempt, 1, 'intent', 'claim', 'qualification', "
            "'role/deployer', :token_hash, CURRENT_TIMESTAMP, :digest, :digest)"
        ), {
            "id": uuid4().hex, "change": change_id, "attempt": uuid4().hex,
            "token_hash": "a" * 64, "digest": "0" * 64,
        })
        with pytest.raises(RuntimeError, match="reconcile"):
            migrate(conn, downgrade=True)
        assert conn.scalar(text("SELECT COUNT(*) FROM platform_deployment_worker_audit")) == 1
        conn.execute(text("DELETE FROM platform_deployment_worker_audit"))
        migrate(conn, downgrade=True)
        assert conn.scalar(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='platform_deployment_worker_audit'"
        )) == 0
