"""Workspace member detail projection using existing authoritative records.

Last login is an account-level timestamp, not workspace-specific activity. Team
membership is intentionally omitted until teams have persisted membership.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.models import User, WorkspaceMembership, WorkspaceRole
from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState
from northstar_api.modules.workspace.services.member_provenance import current_membership_inviter
from northstar_api.schemas import APIModel
from northstar_api.security import Principal
from northstar_api.workspace_invitations import WorkspaceInvitation, WorkspaceInvitationStatus

router = APIRouter(prefix="/workspace/members", tags=["workspace members"])
MemberViewPrincipal = Annotated[Principal, Depends(require_permissions("members.view"))]


class WorkspaceMemberDetailsOut(APIModel):
    user_id: UUID
    name: str
    email: str
    role: WorkspaceRole
    status: Literal["active", "suspended"]
    mfa_enabled: bool
    last_login_at: datetime | None
    invited_by_user_id: UUID | None
    joined_at: datetime


@router.get("/details", response_model=list[WorkspaceMemberDetailsOut])
async def list_member_details(
    principal: MemberViewPrincipal, session: DBSession,
) -> list[WorkspaceMemberDetailsOut]:
    """Return members of the selected tenant/workspace, never global user lists.

    ``lastLoginAt`` describes account sign-in, not last Workspace activity;
    ``invitedByUserId`` is null if the current membership cannot be related to
    a recent accepted invitation (for example after removal and direct re-add).
    """
    assert principal.workspace_id is not None
    tenant_id, workspace_id = principal.tenant_id, principal.workspace_id
    rows = (await session.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.workspace_id == workspace_id,
            User.is_active.is_(True),
        )
        .order_by(WorkspaceMembership.created_at, User.email)
    )).all()
    if not rows:
        return []
    user_ids = [membership.user_id for membership, _ in rows]
    joined_at_by_user = {membership.user_id: membership.created_at for membership, _ in rows}
    suspended = set(await session.scalars(
        select(WorkspaceMemberState.user_id).where(
            WorkspaceMemberState.tenant_id == tenant_id,
            WorkspaceMemberState.workspace_id == workspace_id,
            WorkspaceMemberState.user_id.in_(user_ids),
            WorkspaceMemberState.suspended_at.is_not(None),
        )
    ))
    # An earlier accepted invitation cannot establish who invited a membership
    # that was subsequently removed and re-added. Match the current join time.
    invitations = (await session.execute(
        select(
            WorkspaceInvitation.accepted_by_user_id,
            WorkspaceInvitation.invited_by_user_id,
            WorkspaceInvitation.accepted_at,
        )
        .where(
            WorkspaceInvitation.tenant_id == tenant_id,
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.accepted_by_user_id.in_(user_ids),
            WorkspaceInvitation.status == WorkspaceInvitationStatus.ACCEPTED,
        )
        .order_by(WorkspaceInvitation.accepted_at.desc())
    )).all()
    invited_by: dict[UUID, UUID] = {}
    for user_id, inviter_id, accepted_at in invitations:
        if user_id is None or user_id in invited_by:
            continue
        inviter = current_membership_inviter(
            joined_at=joined_at_by_user[user_id],
            accepted_at=accepted_at,
            inviter_id=inviter_id,
        )
        if inviter is not None:
            invited_by[user_id] = inviter
    return [
        WorkspaceMemberDetailsOut(
            user_id=membership.user_id,
            name=user.name,
            email=user.email,
            role=membership.role,
            status="suspended" if membership.user_id in suspended else "active",
            mfa_enabled=user.mfa_enabled,
            last_login_at=user.last_login_at,
            invited_by_user_id=invited_by.get(membership.user_id),
            joined_at=membership.created_at,
        )
        for membership, user in rows
    ]
