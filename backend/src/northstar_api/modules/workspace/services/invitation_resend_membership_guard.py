"""Read-only, tenant-scoped safety check for protected invitation resends.

A pending invitation may become stale after a member joins through another
administrative path. Do not email a newly rotated credential to an existing
member. The invitation service still owns the transaction and remains the
source of truth for token rotation and all other resend validations.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select

from northstar_api.dependencies import CurrentPrincipal, DBSession
from northstar_api.models import User, WorkspaceMembership
from northstar_api.workspace_invitations import WorkspaceInvitation


async def prevent_resend_to_existing_workspace_member(
    request: Request, principal: CurrentPrincipal, session: DBSession,
) -> None:
    """Reject a known member without altering invitations or legacy routes.

    Avoid an invitation-existence oracle: unauthorized, unselected and invalid
    requests continue to the endpoint's established permission/404/422 handling.
    This early read reduces stale resends; it is not a substitute for a locked
    service-level check during concurrent membership and acceptance changes.
    """
    if (
        request.method != "POST"
        or principal.workspace_id is None
        or "members.manage" not in principal.permissions
    ):
        return
    route = request.scope.get("route")
    if getattr(route, "path", "") .endswith(
        "/workspace/invitations/{invitation_id}/resend"
    ) is False:
        return
    try:
        invitation_id = UUID(str(request.path_params.get("invitation_id", "")))
    except (ValueError, TypeError):
        return
    invitation_email = await session.scalar(
        select(WorkspaceInvitation.email).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.tenant_id == principal.tenant_id,
            WorkspaceInvitation.workspace_id == principal.workspace_id,
        )
    )
    if invitation_email is None:
        return
    existing_member_id = await session.scalar(
        select(WorkspaceMembership.user_id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.tenant_id == principal.tenant_id,
            WorkspaceMembership.workspace_id == principal.workspace_id,
            func.lower(User.email) == invitation_email,
        )
    )
    if existing_member_id is not None:
        raise HTTPException(
            status_code=409,
            detail="This email address is already a member of the workspace",
        )
