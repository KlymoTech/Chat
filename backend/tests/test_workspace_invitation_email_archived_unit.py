"""Archived workspaces must not retain or republish pending invite credentials."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import Base
from northstar_api.models import Tenant, User, Workspace, WorkspaceStatus
from northstar_api.modules.workspace.models.invitation_email_job import WorkspaceInvitationEmailJob
from northstar_api.modules.workspace.services.invitation_email_delivery import (
    cancel_obsolete_invitation_email_jobs,
)
from northstar_api.workspace_invitations import WorkspaceInvitation, WorkspaceInvitationStatus


class _SyncExecutor:
    """Run the async cleanup against a real SQLite transaction."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    async def execute(self, statement):
        return self.connection.execute(statement)


@pytest.mark.asyncio
async def test_archived_workspace_jobs_are_scrubbed_but_active_workspace_jobs_survive() -> None:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, User.__table__, Workspace.__table__,
        WorkspaceInvitation.__table__, WorkspaceInvitationEmailJob.__table__,
    ])
    now = datetime.now(UTC)
    tenant_id = uuid4()
    jobs = WorkspaceInvitationEmailJob.__table__
    states: dict[str, object] = {}
    with engine.begin() as connection:
        connection.execute(Tenant.__table__.insert().values(
            id=tenant_id, slug=f"invite-archive-{uuid4().hex[:10]}", name="Invite archive test",
        ))
        for name, status, job_status in (
            ("archived-queued", WorkspaceStatus.ARCHIVED, "queued"),
            ("archived-retry", WorkspaceStatus.ARCHIVED, "failed"),
            ("active-queued", WorkspaceStatus.ACTIVE, "queued"),
        ):
            workspace_id, invitation_id, job_id = uuid4(), uuid4(), uuid4()
            connection.execute(Workspace.__table__.insert().values(
                id=workspace_id, tenant_id=tenant_id, name=name,
                slug=f"archive-{uuid4().hex[:10]}", status=status,
            ))
            connection.execute(WorkspaceInvitation.__table__.insert().values(
                id=invitation_id, tenant_id=tenant_id, workspace_id=workspace_id,
                email=f"{name}-{uuid4().hex}@example.com", token_hash="a" * 64,
                status=WorkspaceInvitationStatus.PENDING,
                expires_at=now + timedelta(days=1),
            ))
            connection.execute(jobs.insert().values(
                id=job_id, tenant_id=tenant_id, workspace_id=workspace_id,
                invitation_id=invitation_id, token_hash="a" * 64,
                ciphertext="encrypted-pending-credential", status=job_status,
            ))
            states[name] = job_id

    with engine.begin() as connection:
        scoped_session = cast(AsyncSession, _SyncExecutor(connection))
        await cancel_obsolete_invitation_email_jobs(scoped_session, now=now)
        actual = dict((job_id, (status, ciphertext)) for job_id, status, ciphertext in
                      connection.execute(select(jobs.c.id, jobs.c.status, jobs.c.ciphertext)))
        for name in ("archived-queued", "archived-retry"):
            assert actual[states[name]] == ("cancelled", None), name
        assert actual[states["active-queued"]] == ("queued", "encrypted-pending-credential")
        await cancel_obsolete_invitation_email_jobs(scoped_session, now=now)
        assert dict((job_id, (status, ciphertext)) for job_id, status, ciphertext in
                    connection.execute(select(jobs.c.id, jobs.c.status, jobs.c.ciphertext))) == actual
    engine.dispose()
