"""Expired, revoked, accepted or superseded invite jobs must not retain secrets."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import Base
from northstar_api.models import Tenant, User, Workspace
from northstar_api.modules.workspace.models.invitation_email_job import WorkspaceInvitationEmailJob
from northstar_api.modules.workspace.services.invitation_email_delivery import (
    cancel_obsolete_invitation_email_jobs,
)
from northstar_api.workspace_invitations import WorkspaceInvitation, WorkspaceInvitationStatus


class _SyncExecutor:
    """Exercise the async cleanup function against a real SQLite transaction."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def execute(self, statement):
        return self.connection.execute(statement)


@pytest.mark.asyncio
async def test_obsolete_jobs_are_cancelled_without_touching_current_or_sent_jobs() -> None:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, User.__table__, Workspace.__table__,
        WorkspaceInvitation.__table__, WorkspaceInvitationEmailJob.__table__,
    ])
    now = datetime.now(UTC)
    tenants = [uuid4(), uuid4()]
    workspaces = [uuid4(), uuid4()]
    invitations, jobs = WorkspaceInvitation.__table__, WorkspaceInvitationEmailJob.__table__
    expected: dict[str, tuple[str, str | None]] = {}
    ids: dict[str, object] = {}

    with engine.begin() as connection:
        for index, (tenant_id, workspace_id) in enumerate(zip(tenants, workspaces, strict=True)):
            connection.execute(Tenant.__table__.insert().values(
                id=tenant_id, name=f"Tenant {index}", slug=f"tenant-{uuid4().hex[:10]}",
            ))
            connection.execute(Workspace.__table__.insert().values(
                id=workspace_id, tenant_id=tenant_id,
                name=f"Workspace {index}", slug=f"workspace-{uuid4().hex[:10]}",
            ))
        for index, (case, tenant_index, status, expires_at, job_status) in enumerate((
            ("current", 0, WorkspaceInvitationStatus.PENDING, now + timedelta(days=1), "queued"),
            ("revoked", 0, WorkspaceInvitationStatus.REVOKED, now + timedelta(days=1), "queued"),
            ("accepted", 0, WorkspaceInvitationStatus.ACCEPTED, now + timedelta(days=1), "failed"),
            ("expired", 0, WorkspaceInvitationStatus.PENDING, now - timedelta(minutes=1), "queued"),
            ("superseded", 0, WorkspaceInvitationStatus.PENDING, now + timedelta(days=1), "queued"),
            ("already-sent", 0, WorkspaceInvitationStatus.PENDING, now + timedelta(days=1), "sent"),
            ("other-tenant", 1, WorkspaceInvitationStatus.PENDING, now + timedelta(days=1), "queued"),
        )):
            invitation_id, job_id = uuid4(), uuid4()
            fingerprint = f"{index + 1}" * 64
            job_fingerprint = "f" * 64 if case == "superseded" else fingerprint
            connection.execute(invitations.insert().values(
                id=invitation_id, tenant_id=tenants[tenant_index],
                workspace_id=workspaces[tenant_index],
                email=f"{case}-{uuid4().hex}@example.com", token_hash=fingerprint,
                status=status, expires_at=expires_at,
            ))
            connection.execute(jobs.insert().values(
                id=job_id, tenant_id=tenants[tenant_index],
                workspace_id=workspaces[tenant_index], invitation_id=invitation_id,
                token_hash=job_fingerprint, ciphertext="encrypted-secret", status=job_status,
            ))
            ids[case] = job_id
            expected[case] = (
                ("queued" if case in {"current", "other-tenant"} else "sent")
                if case in {"current", "other-tenant", "already-sent"} else "cancelled",
                "encrypted-secret" if case in {"current", "other-tenant", "already-sent"} else None,
            )
        # Foreign keys alone permit a tenant ID that does not match the
        # referenced invitation. The cleanup must not treat it as deliverable.
        mismatch = uuid4()
        connection.execute(jobs.insert().values(
            id=mismatch, tenant_id=tenants[1], workspace_id=workspaces[0],
            invitation_id=next(iter(connection.execute(select(invitations.c.id).where(
                invitations.c.tenant_id == tenants[0],
            ))))[0],
            token_hash="1" * 64, ciphertext="encrypted-secret", status="queued",
        ))
        ids["mismatched-tenant"] = mismatch
        expected["mismatched-tenant"] = ("cancelled", None)

    with engine.begin() as connection:
        await cancel_obsolete_invitation_email_jobs(
            cast(AsyncSession, _SyncExecutor(connection)), now=now,
        )
        rows = dict((id_, (status, ciphertext)) for id_, status, ciphertext in connection.execute(
            select(jobs.c.id, jobs.c.status, jobs.c.ciphertext)
        ))
        for case, job_id in ids.items():
            assert rows[job_id] == expected[case], case
        # Repeated cycles must be safe and must not touch valid records.
        await cancel_obsolete_invitation_email_jobs(
            cast(AsyncSession, _SyncExecutor(connection)), now=now,
        )
        assert dict((id_, (status, ciphertext)) for id_, status, ciphertext in connection.execute(
            select(jobs.c.id, jobs.c.status, jobs.c.ciphertext)
        )) == rows
    engine.dispose()
