"""Execute the additive migration, independently of ORM metadata.create_all()."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = Path(__file__).parents[1] / "migrations/versions/0054_knowledge_audit_tables.py"


def _migration():
    spec = importlib.util.spec_from_file_location("knowledge_audit_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migrated_connection():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata = sa.MetaData()
        for name in ("tenants", "workspaces", "agents", "messages"):
            sa.Table(name, metadata, sa.Column("id", sa.Uuid(), primary_key=True))
        metadata.create_all(connection)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        yield connection
    engine.dispose()


def _tables(connection):
    metadata = sa.MetaData()
    metadata.reflect(connection)
    return metadata.tables


def _seed(connection):
    tables = _tables(connection)
    ids = {}
    for name in ("tenants", "workspaces", "agents", "messages"):
        ids[name] = uuid4().hex
        connection.execute(tables[name].insert().values(id=ids[name]))
    owner = {"tenant_id": ids["tenants"], "workspace_id": ids["workspaces"], "agent_id": ids["agents"]}
    snapshot_id, audit_id = uuid4().hex, uuid4().hex
    connection.execute(tables["knowledge_snapshots"].insert().values(
        id=snapshot_id, revision=1, manifest={"sources": []}, **owner
    ))
    connection.execute(tables["knowledge_answer_audits"].insert().values(
        id=audit_id, message_id=ids["messages"], snapshot_id=snapshot_id,
        details={"mode": "approved_knowledge_only"}, **owner
    ))
    return tables, ids, owner, snapshot_id, audit_id


def test_upgrade_creates_expected_columns_and_indexes(migrated_connection):
    inspector = sa.inspect(migrated_connection)
    common = {"id", "tenant_id", "workspace_id", "agent_id", "created_at", "updated_at"}
    for name, extra in (
        ("knowledge_snapshots", {"revision", "manifest"}),
        ("knowledge_answer_audits", {"message_id", "snapshot_id", "details"}),
    ):
        assert {column["name"] for column in inspector.get_columns(name)} == common | extra
        assert {tuple(index["column_names"]) for index in inspector.get_indexes(name)} == {
            ("tenant_id",), ("workspace_id",), ("agent_id",)
        }


def test_snapshot_identity_is_unique(migrated_connection):
    tables, _, owner, _, _ = _seed(migrated_connection)
    with pytest.raises(sa.exc.IntegrityError):
        migrated_connection.execute(tables["knowledge_snapshots"].insert().values(
            id=uuid4().hex, revision=1, manifest={}, **owner
        ))


def test_missing_owner_is_rejected(migrated_connection):
    tables = _tables(migrated_connection)
    with pytest.raises(sa.exc.IntegrityError):
        migrated_connection.execute(tables["knowledge_snapshots"].insert().values(
            id=uuid4().hex, tenant_id=uuid4().hex, workspace_id=uuid4().hex, agent_id=uuid4().hex, revision=1, manifest={}
        ))


def test_reference_removal_preserves_answer_audit(migrated_connection):
    tables, ids, _, snapshot_id, audit_id = _seed(migrated_connection)
    migrated_connection.execute(tables["messages"].delete().where(tables["messages"].c.id == ids["messages"]))
    migrated_connection.execute(tables["knowledge_snapshots"].delete().where(
        tables["knowledge_snapshots"].c.id == snapshot_id
    ))
    row = migrated_connection.execute(sa.select(tables["knowledge_answer_audits"]).where(
        tables["knowledge_answer_audits"].c.id == audit_id
    )).mappings().one()
    assert row["message_id"] is None and row["snapshot_id"] is None
    assert row["details"] == {"mode": "approved_knowledge_only"}


def test_tenant_removal_cascades(migrated_connection):
    tables, ids, _, _, _ = _seed(migrated_connection)
    migrated_connection.execute(tables["tenants"].delete().where(tables["tenants"].c.id == ids["tenants"]))
    for name in ("knowledge_snapshots", "knowledge_answer_audits"):
        assert migrated_connection.scalar(sa.select(sa.func.count()).select_from(tables[name])) == 0


def test_downgrade_removes_only_new_tables(migrated_connection):
    with Operations.context(MigrationContext.configure(migrated_connection)):
        _migration().downgrade()
    assert set(sa.inspect(migrated_connection).get_table_names()) == {"tenants", "workspaces", "agents", "messages"}


def test_postgresql_ddl_includes_jsonb_rls_and_runtime_grants():
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        _migration().upgrade()
    sql = output.getvalue()
    for table in ("knowledge_snapshots", "knowledge_answer_audits"):
        assert f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in sql
        assert f'CREATE POLICY tenant_isolation ON "{table}"' in sql
        assert f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO northstar_app' in sql
    assert "manifest JSONB" in sql and "details JSONB" in sql
    assert sql.count("WITH CHECK") == 2
    assert "ON DELETE SET NULL" in sql
    assert _migration().down_revision == "0053_bot_workflow_builder"
