"""Exercise the Workspace invite-mail grant migration without a live database."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/0058_workspace_invitation_email_service_access.py"
)


class _MigrationOperations:
    def __init__(self, dialect: str) -> None:
        self.dialect = dialect
        self.statements: list[str] = []

    def get_bind(self) -> SimpleNamespace:
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def _load_migration(monkeypatch: pytest.MonkeyPatch, dialect: str):
    spec = importlib.util.spec_from_file_location("workspace_invite_mail_service_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operations = _MigrationOperations(dialect)
    monkeypatch.setattr(migration, "op", operations)
    return migration, operations


def test_postgresql_service_grant_is_scoped_and_reversible(monkeypatch: pytest.MonkeyPatch) -> None:
    migration, operations = _load_migration(monkeypatch, "postgresql")
    assert migration.down_revision == "0057_workspace_invite_email_jobs"
    migration.upgrade()
    assert operations.statements == [
        'GRANT SELECT, UPDATE ON "workspace_invitation_email_jobs" TO "northstar_service"'
    ]
    migration.downgrade()
    assert operations.statements[-1] == (
        'REVOKE SELECT, UPDATE ON "workspace_invitation_email_jobs" FROM "northstar_service"'
    )
    assert len(operations.statements) == 2


def test_sqlite_upgrade_and_downgrade_do_not_change_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    migration, operations = _load_migration(monkeypatch, "sqlite")
    migration.upgrade()
    migration.downgrade()
    assert operations.statements == []
