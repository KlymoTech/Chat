"""Deployment worker PostgreSQL identity and least-privilege startup gate.

This gate rejects shared customer API credentials, high-privilege PostgreSQL
roles and mutable audit history. It does not provision roles or grant privileges:
an operator must provision the dedicated DB login out-of-band.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

_ROLE = re.compile(r"^[a-z_][a-z0-9_]{2,62}$")


class WorkerDatabaseSecurityError(RuntimeError):
    """Database identity is not qualified to serve machine deployment calls."""


@dataclass(frozen=True)
class WorkerDatabaseConfig:
    database_url: str
    expected_role: str

    @classmethod
    def from_environment(cls, values: Mapping[str, str], *, public_database_url: str):
        address = values.get("NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_URL", "")
        role = values.get("NORTHSTAR_DEPLOYMENT_WORKER_DATABASE_ROLE", "")
        if not address or not role or address == public_database_url:
            raise WorkerDatabaseSecurityError("isolated worker database credentials are required")
        if not _ROLE.fullmatch(role) or role in {"postgres", "northstar", "northstar_app"}:
            raise WorkerDatabaseSecurityError("dedicated worker database role is required")
        try:
            worker_url = make_url(address)
            customer_url = make_url(public_database_url)
        except (ValueError, TypeError) as exc:
            raise WorkerDatabaseSecurityError("invalid worker database configuration") from exc
        if (
            worker_url.drivername != "postgresql+asyncpg"
            or worker_url.username is None
            or worker_url.username != role
            or worker_url.password is None
            or not worker_url.password
            or worker_url.host is None
            or (
                worker_url.username == customer_url.username
                and worker_url.host == customer_url.host
                and worker_url.database == customer_url.database
            )
        ):
            raise WorkerDatabaseSecurityError("worker must have separate PostgreSQL login credentials")
        return cls(address, role)


def qualify_worker_database_identity(fields: Mapping[str, Any], *, expected_role: str) -> None:
    """Fail closed for owner/elevated roles or any permission to mutate audit."""
    if (
        fields.get("current_role") != expected_role
        or fields.get("session_role") != expected_role
        or any(fields.get(name) is not False for name in (
            "is_superuser", "can_create_roles", "can_create_databases",
            "can_bypass_rls", "can_replicate", "can_create_schema",
            "can_create_database", "can_write_all_data", "can_read_server_files",
            "can_write_server_files", "can_execute_server_program",
            "audit_update", "audit_delete", "audit_truncate",
            "change_insert", "change_update", "change_delete", "change_truncate",
            "config_insert", "config_update", "config_delete", "config_truncate",
            "lease_insert", "lease_delete", "lease_truncate",
            "step_delete", "step_truncate",
        ))
        or any(fields.get(name) is not True for name in (
            "audit_select", "audit_insert",
            "lease_select", "lease_update",
            "step_select", "step_insert", "step_update",
            "change_select", "config_select",
        ))
    ):
        raise WorkerDatabaseSecurityError("worker PostgreSQL role is not least-privilege")


async def verify_worker_database_identity(engine: AsyncEngine, *, expected_role: str) -> None:
    """Execute the authorization probe in the actual deployment DB session.

    The role cannot pass by SET ROLE: both session_user and current_user must
    be exactly the configured dedicated login.
    """
    if engine.dialect.name != "postgresql":
        raise WorkerDatabaseSecurityError("deployment worker requires PostgreSQL")
    probe = text("""
        SELECT
            current_user AS current_role,
            session_user AS session_role,
            r.rolsuper AS is_superuser,
            r.rolcreaterole AS can_create_roles,
            r.rolcreatedb AS can_create_databases,
            r.rolbypassrls AS can_bypass_rls,
            r.rolreplication AS can_replicate,
            has_schema_privilege(current_user, current_schema(), 'CREATE') AS can_create_schema,
            has_database_privilege(current_user, current_database(), 'CREATE') AS can_create_database,
            pg_has_role(current_user, 'pg_write_all_data', 'member') AS can_write_all_data,
            pg_has_role(current_user, 'pg_read_server_files', 'member') AS can_read_server_files,
            pg_has_role(current_user, 'pg_write_server_files', 'member') AS can_write_server_files,
            pg_has_role(current_user, 'pg_execute_server_program', 'member') AS can_execute_server_program,
            has_table_privilege(current_user, 'platform_deployment_worker_audit', 'SELECT')
                AS audit_select,
            has_table_privilege(current_user, 'platform_deployment_worker_audit', 'INSERT')
                AS audit_insert,
            has_table_privilege(current_user, 'platform_deployment_worker_audit', 'UPDATE')
                AS audit_update,
            has_table_privilege(current_user, 'platform_deployment_worker_audit', 'DELETE')
                AS audit_delete,
            has_table_privilege(current_user, 'platform_deployment_worker_audit', 'TRUNCATE')
                AS audit_truncate,
            has_table_privilege(current_user, 'platform_deployment_leases', 'SELECT')
                AS lease_select,
            has_table_privilege(current_user, 'platform_deployment_leases', 'UPDATE')
                AS lease_update,
            has_table_privilege(current_user, 'platform_deployment_steps', 'SELECT')
                AS step_select,
            has_table_privilege(current_user, 'platform_deployment_steps', 'INSERT')
                AS step_insert,
            has_table_privilege(current_user, 'platform_deployment_steps', 'UPDATE')
                AS step_update,
            has_table_privilege(current_user, 'platform_changes', 'SELECT')
                AS change_select,
            has_table_privilege(current_user, 'platform_changes', 'INSERT')
                AS change_insert,
            has_table_privilege(current_user, 'platform_changes', 'UPDATE')
                AS change_update,
            has_table_privilege(current_user, 'platform_changes', 'DELETE')
                AS change_delete,
            has_table_privilege(current_user, 'platform_changes', 'TRUNCATE')
                AS change_truncate,
            has_table_privilege(current_user, 'platform_config_versions', 'SELECT')
                AS config_select,
            has_table_privilege(current_user, 'platform_config_versions', 'INSERT')
                AS config_insert,
            has_table_privilege(current_user, 'platform_config_versions', 'UPDATE')
                AS config_update,
            has_table_privilege(current_user, 'platform_config_versions', 'DELETE')
                AS config_delete,
            has_table_privilege(current_user, 'platform_config_versions', 'TRUNCATE')
                AS config_truncate,
            has_table_privilege(current_user, 'platform_deployment_leases', 'INSERT')
                AS lease_insert,
            has_table_privilege(current_user, 'platform_deployment_leases', 'DELETE')
                AS lease_delete,
            has_table_privilege(current_user, 'platform_deployment_leases', 'TRUNCATE')
                AS lease_truncate,
            has_table_privilege(current_user, 'platform_deployment_steps', 'DELETE')
                AS step_delete,
            has_table_privilege(current_user, 'platform_deployment_steps', 'TRUNCATE')
                AS step_truncate
        FROM pg_roles r WHERE r.rolname = current_user
    """)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(probe)
            record = result.mappings().one()
    except Exception as exc:
        raise WorkerDatabaseSecurityError("unable to qualify worker PostgreSQL permissions") from exc
    qualify_worker_database_identity(record, expected_role=expected_role)
