"""Dedicated PostgreSQL role guard must reject shared or privileged DB access."""
from types import SimpleNamespace

import pytest

from northstar_api.modules.platform_runtime.deployment_worker_database import (
    WorkerDatabaseConfig,
    WorkerDatabaseSecurityError,
    qualify_worker_database_identity,
    verify_worker_database_identity,
)

APP_URL = "postgresql+asyncpg://northstar:app-secret@db.internal/northstar"
WORKER_URL = "postgresql+asyncpg://northstar_deployer:worker-secret@db.internal/northstar"
ROLE = "northstar_deployer"


def safe_role():
    return {
        "current_role": ROLE,
        "session_role": ROLE,
        "is_superuser": False,
        "can_create_roles": False,
        "can_create_databases": False,
        "can_bypass_rls": False,
        "can_replicate": False,
        "can_create_schema": False,
        "can_create_database": False,
        "can_write_all_data": False,
        "can_read_server_files": False,
        "can_write_server_files": False,
        "can_execute_server_program": False,
        "audit_update": False,
        "audit_delete": False,
        "audit_truncate": False,
        "audit_select": True,
        "audit_insert": True,
        "lease_select": True,
        "lease_update": True,
        "step_select": True,
        "step_insert": True,
        "step_update": True,
        "change_select": True,
    }


def test_explicit_worker_database_separate_from_customer_login():
    config = WorkerDatabaseConfig.from_environment({
        "NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_URL": WORKER_URL,
        "NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_ROLE": ROLE,
    }, public_database_url=APP_URL)
    assert config.expected_role == ROLE
    assert config.database_url == WORKER_URL
    qualify_worker_database_identity(safe_role(), expected_role=ROLE)


@pytest.mark.parametrize("worker_url,role", [
    (APP_URL, "northstar"),
    ("", ROLE),
    ("sqlite+aiosqlite:///worker.db", ROLE),
    ("postgresql+asyncpg://northstar:worker-secret@db.internal/northstar", "northstar"),
    ("postgresql+asyncpg://northstar:worker-secret@db.internal/northstar", ROLE),
    (WORKER_URL, "postgres"),
    (WORKER_URL, "northstar_app"),
    (WORKER_URL, "northstar-worker"),
    ("postgresql+asyncpg://northstar_deployer@db.internal/northstar", ROLE),
])
def test_unsafe_worker_dsn_or_login_refused(worker_url, role):
    with pytest.raises(WorkerDatabaseSecurityError):
        WorkerDatabaseConfig.from_environment({
            "NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_URL": worker_url,
            "NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_ROLE": role,
        }, public_database_url=APP_URL)


@pytest.mark.parametrize("field,value", [
    ("current_role", "northstar_app"),
    ("session_role", "postgres"),
    ("is_superuser", True),
    ("can_create_roles", True),
    ("can_create_databases", True),
    ("can_bypass_rls", True),
    ("can_replicate", True),
    ("can_create_schema", True),
    ("can_create_database", True),
    ("can_write_all_data", True),
    ("can_read_server_files", True),
    ("can_write_server_files", True),
    ("can_execute_server_program", True),
    ("audit_update", True),
    ("audit_delete", True),
    ("audit_truncate", True),
    ("audit_select", False),
    ("audit_insert", False),
    ("lease_select", False),
    ("lease_update", False),
    ("step_select", False),
    ("step_insert", False),
    ("step_update", False),
    ("change_select", False),
])
def test_unqualified_pg_role_denied(field, value):
    info = safe_role()
    info[field] = value
    with pytest.raises(WorkerDatabaseSecurityError, match="least-privilege"):
        qualify_worker_database_identity(info, expected_role=ROLE)


def test_missing_probe_field_fail_closed():
    info = safe_role()
    del info["audit_delete"]
    with pytest.raises(WorkerDatabaseSecurityError):
        qualify_worker_database_identity(info, expected_role=ROLE)


class _ProbeResult:
    def __init__(self, values):
        self.values = values

    def mappings(self):
        return self

    def one(self):
        return self.values


class _Connection:
    def __init__(self, fields):
        self.fields = fields
        self.executed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, _kind, _error, _trace):
        return False

    async def execute(self, statement):
        assert "pg_roles" in str(statement)
        self.executed = True
        return _ProbeResult(self.fields)


class _Engine:
    def __init__(self, fields, dialect="postgresql"):
        self.dialect = SimpleNamespace(name=dialect)
        self.connection = _Connection(fields)

    def connect(self):
        return self.connection


@pytest.mark.asyncio
async def test_database_identity_uses_live_connection_probe():
    engine = _Engine(safe_role())
    await verify_worker_database_identity(engine, expected_role=ROLE)
    assert engine.connection.executed


@pytest.mark.asyncio
async def test_database_identity_fails_closed_without_postgres():
    engine = _Engine(safe_role(), dialect="sqlite")
    with pytest.raises(WorkerDatabaseSecurityError, match="PostgreSQL"):
        await verify_worker_database_identity(engine, expected_role=ROLE)
    assert not engine.connection.executed


@pytest.mark.asyncio
async def test_database_identity_rejects_actual_superuser_response():
    info = safe_role()
    info["is_superuser"] = True
    with pytest.raises(WorkerDatabaseSecurityError, match="least-privilege"):
        await verify_worker_database_identity(_Engine(info), expected_role=ROLE)
