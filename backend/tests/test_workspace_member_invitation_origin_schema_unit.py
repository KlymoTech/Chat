"""SQL-level foreign-key and lifecycle regression for invitation provenance."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError

from northstar_api.database import Base
from northstar_api.models import Tenant, User, Workspace, WorkspaceMembership
from northstar_api.modules.workspace.models.member_invitation_origin import WorkspaceMemberInvitationOrigin
from northstar_api.workspace_invitations import WorkspaceInvitation


def test_current_membership_origin_constraints_and_cascade() -> None:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, User.__table__, Workspace.__table__,
        WorkspaceMembership.__table__, WorkspaceInvitation.__table__,
        WorkspaceMemberInvitationOrigin.__table__,
    ])
    tenant_id, workspace_id, member_id, inviter_id, invitation_id = (uuid4() for _ in range(5))
    tenant, workspace = Tenant.__table__, Workspace.__table__
    users, memberships = User.__table__, WorkspaceMembership.__table__
    invitations, origins = WorkspaceInvitation.__table__, WorkspaceMemberInvitationOrigin.__table__
    with engine.begin() as connection:
        connection.execute(tenant.insert().values(id=tenant_id, slug=f"t-{uuid4().hex[:12]}", name="Tenant"))
        connection.execute(users.insert(), [
            {"id": inviter_id, "email": f"inviter-{uuid4().hex}@example.com", "name": "Inviter", "password_hash": "test"},
            {"id": member_id, "email": f"invitee-{uuid4().hex}@example.com", "name": "Invitee", "password_hash": "test"},
        ])
        connection.execute(workspace.insert().values(
            id=workspace_id, tenant_id=tenant_id, name="Workspace", slug=f"w-{uuid4().hex[:12]}",
        ))
        connection.execute(invitations.insert().values(
            id=invitation_id, tenant_id=tenant_id, workspace_id=workspace_id,
            email=f"invited-{uuid4().hex}@example.com", token_hash=uuid4().hex * 2,
            invited_by_user_id=inviter_id, expires_at=datetime.now(UTC) + timedelta(days=1),
        ))

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(origins.insert().values(
                tenant_id=tenant_id, workspace_id=workspace_id,
                user_id=member_id, invitation_id=invitation_id,
            ))

    with engine.begin() as connection:
        connection.execute(memberships.insert().values(
            workspace_id=workspace_id, user_id=member_id, tenant_id=tenant_id,
        ))
        connection.execute(origins.insert().values(
            tenant_id=tenant_id, workspace_id=workspace_id,
            user_id=member_id, invitation_id=invitation_id,
        ))
    with engine.connect() as connection:
        assert connection.scalar(select(origins.c.invitation_id)) == invitation_id

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(origins.insert().values(
                tenant_id=tenant_id, workspace_id=uuid4(),
                user_id=uuid4(), invitation_id=invitation_id,
            ))

    with engine.begin() as connection:
        connection.execute(memberships.delete().where(
            memberships.c.workspace_id == workspace_id, memberships.c.user_id == member_id,
        ))
    with engine.connect() as connection:
        assert connection.scalar(select(origins.c.invitation_id)) is None
        assert connection.scalar(select(invitations.c.id)) == invitation_id
    engine.dispose()
