"""SQL-level constraints for independently encrypted Workspace invite delivery."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError

from northstar_api.database import Base
from northstar_api.models import Tenant, User, Workspace
from northstar_api.modules.workspace.models.invitation_email_job import WorkspaceInvitationEmailJob
from northstar_api.workspace_invitations import WorkspaceInvitation


def test_invitation_email_job_has_scoped_foreign_keys_and_cascades() -> None:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, User.__table__, Workspace.__table__,
        WorkspaceInvitation.__table__, WorkspaceInvitationEmailJob.__table__,
    ])
    tenant_id, workspace_id, inviter_id, invitation_id, job_id = (uuid4() for _ in range(5))
    tenant, workspace, user = Tenant.__table__, Workspace.__table__, User.__table__
    invitations, jobs = WorkspaceInvitation.__table__, WorkspaceInvitationEmailJob.__table__
    with engine.begin() as connection:
        connection.execute(tenant.insert().values(
            id=tenant_id, name="Tenant", slug=f"tenant-{uuid4().hex[:12]}",
        ))
        connection.execute(user.insert().values(
            id=inviter_id, email=f"inviter-{uuid4().hex}@example.com",
            name="Inviter", password_hash="test",
        ))
        connection.execute(workspace.insert().values(
            id=workspace_id, tenant_id=tenant_id, name="Workspace", slug=f"w-{uuid4().hex[:12]}",
        ))
        connection.execute(invitations.insert().values(
            id=invitation_id, tenant_id=tenant_id, workspace_id=workspace_id,
            email=f"recipient-{uuid4().hex}@example.com", invited_by_user_id=inviter_id,
            token_hash="a" * 64, expires_at=datetime.now(UTC) + timedelta(days=1),
        ))
        connection.execute(jobs.insert().values(
            id=job_id, tenant_id=tenant_id, workspace_id=workspace_id,
            invitation_id=invitation_id, token_hash="a" * 64,
            ciphertext="encrypted-not-plaintext",
        ))
    indexes = {index["name"] for index in inspect(engine).get_indexes("workspace_invitation_email_jobs")}
    assert "ix_workspace_invitation_email_jobs_tenant_workspace" in indexes
    assert "ix_workspace_invitation_email_jobs_dispatch" in indexes
    with engine.connect() as connection:
        assert connection.scalar(select(jobs.c.ciphertext)) == "encrypted-not-plaintext"
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(jobs.insert().values(
                id=uuid4(), tenant_id=tenant_id, workspace_id=workspace_id,
                invitation_id=uuid4(), token_hash="b" * 64,
            ))
    with engine.begin() as connection:
        connection.execute(invitations.delete().where(invitations.c.id == invitation_id))
    with engine.connect() as connection:
        assert connection.scalar(select(jobs.c.id)) is None
    engine.dispose()
