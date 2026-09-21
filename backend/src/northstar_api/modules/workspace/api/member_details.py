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
from northstar_api.modules.workspace.models.member_invitation_origin import WorkspaceMemberInvitationOrigin
from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState
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
    status: Literal["active", "suspended", "disabled"]
    mfa_enabled: bool
    last_login_at: datetime | None
    invited_by_user_id: UUID | None
    joined_at: datetime


def member_detail_status(
    *, account_active: bool, suspended: bool,
) -> Literal["active", "suspended", "disabled"]:
    """An unavailable global account must never be presented as active."""
    if not account_active:
        return "disabled"
    return "suspended" if suspended else "active"


@router.get("/details", response_model=list[WorkspaceMemberDetailsOut])
async def list_member_details(
    principal: MemberViewPrincipal, session: DBSession,
) -> list[WorkspaceMemberDetailsOut]:
    """Return only current tenant/workspace members and proven invitation origins.

    ``lastLoginAt`` is account-level, not last Workspace activity. Historical
    invitations without a current membership link do not establish an inviter.
    Disabled accounts remain visible to authorized readers but cannot log in.
    """
    assert principal.workspace_id is not None
    tenant_id, workspace_id = principal.tenant_id, principal.workspace_id
    rows = (await session.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
        .order_by(WorkspaceMembership.created_at, User.email)
    )).all()
    if not rows:
        return []
    user_ids = [membership.user_id for membership, _ in rows]
    suspended = set(await session.scalars(
        select(WorkspaceMemberState.user_id).where(
            WorkspaceMemberState.tenant_id == tenant_id,
            WorkspaceMemberState.workspace_id == workspace_id,
            WorkspaceMemberState.user_id.in_(user_ids),
            WorkspaceMemberState.suspended_at.is_not(None),
        )
    ))
    # A link is created only by the invitation acceptance transaction and
    # cascades away with the current membership. Scope and accepted identity
    # are checked again rather than trusting an invitation ID in isolation.
    linked_inviters = (await session.execute(
        select(
            WorkspaceMemberInvitationOrigin.user_id,
            WorkspaceInvitation.invited_by_user_id,
        )
        .join(
            WorkspaceInvitation,
            WorkspaceInvitation.id == WorkspaceMemberInvitationOrigin.invitation_id,
        )
        .where(
            WorkspaceMemberInvitationOrigin.tenant_id == tenant_id,
            WorkspaceMemberInvitationOrigin.workspace_id == workspace_id,
            WorkspaceMemberInvitationOrigin.user_id.in_(user_ids),
            WorkspaceInvitation.tenant_id == tenant_id,
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.status == WorkspaceInvitationStatus.ACCEPTED,
            WorkspaceInvitation.accepted_by_user_id == WorkspaceMemberInvitationOrigin.user_id,
        )
    )).all()
    invited_by: dict[UUID, UUID | None] = dict(linked_inviters)
    return [
        WorkspaceMemberDetailsOut(
            user_id=membership.user_id,
            name=user.name,
            email=user.email,
            role=membership.role,
            status=member_detail_status(
                account_active=user.is_active,
                suspended=membership.user_id in suspended,
            ),
            mfa_enabled=user.mfa_enabled,
            last_login_at=user.last_login_at,
            invited_by_user_id=invited_by.get(membership.user_id),
            joined_at=membership.created_at,
        )
        for membership, user in rows
    ]
