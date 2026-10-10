"""Exercise migration 0079 against a real SQLite schema, not mocked Alembic calls."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0079_platform_single_active_config.py"


def _module():
    spec = importlib.util.spec_from_file_location("single_active_config_0079", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration(connection, *, downgrade: bool = False) -> None:
    module = _module()
    context = MigrationContext.configure(connection)
    operations = Operations(context)
    original = module.op
    module.op = operations
    try:
        if downgrade:
            module.downgrade()
        else:
            module.upgrade()
    finally:
        module.op = original


def _setup(connection) -> None:
    connection.execute(text(
        "CREATE TABLE platform_config_versions (id TEXT PRIMARY KEY, "
        "environment TEXT NOT NULL, active BOOLEAN NOT NULL)"
    ))


def test_migration_blocks_preexisting_duplicate_active_versions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        _setup(connection)
        connection.execute(text(
            "INSERT INTO platform_config_versions VALUES "
            "('a','production',1), ('b','production',1)"
        ))
        with pytest.raises(RuntimeError, match="Multiple active"):
            _run_migration(connection)
        # Migration must not erase either record or create partial schema.
        assert connection.scalar(text("SELECT COUNT(*) FROM platform_config_versions")) == 2
        assert not connection.scalar(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
            "AND name='uq_platform_config_versions_one_active_per_environment'"
        ))


def test_upgrade_enforces_uniqueness_and_downgrade_restores_previous_contract() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        _setup(connection)
        connection.execute(text(
            "INSERT INTO platform_config_versions VALUES "
            "('a','production',1), ('b','production',0), ('c','test',1)"
        ))
        _run_migration(connection)
        # Savepoint avoids invalidating the outer transaction on PostgreSQL.
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text(
                "INSERT INTO platform_config_versions VALUES ('d','production',1)"
            ))
        connection.execute(text(
            "INSERT INTO platform_config_versions VALUES ('e','production',0)"
        ))
        _run_migration(connection, downgrade=True)
        connection.execute(text(
            "INSERT INTO platform_config_versions VALUES ('f','production',1)"
        ))
        assert connection.scalar(text(
            "SELECT COUNT(*) FROM platform_config_versions WHERE environment='production' AND active=1"
        )) == 2
