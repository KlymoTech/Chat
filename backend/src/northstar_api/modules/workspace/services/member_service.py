"""Workspace member lifecycle policy, independent of HTTP route registration.

Call these guards only after the existing tenant-scoped membership loader and
workspace write lock. The caller owns the transaction, audit and outbox.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Workspace, WorkspaceMembership, WorkspaceRole

from northstar_api.modules.workspace.member_state import is_member_suspended, member_statuses


async def ensure_member_status_change_allowed(
    session: AsyncSession,
    workspace: Workspace,
    member_user_id: UUID,
    member_role: WorkspaceRole,
    status: Literal["active", "suspended"],
) -> None:
    """Refuse suspension of the last active Workspace administrator.

    The Workspace row must already be locked by the caller; read the current
    membership roles and the freshly reloaded status document together.
    """
    if member_role != WorkspaceRole.ADMIN or status != "suspended":
        return

    administrator_ids = await session.scalars(
        select(WorkspaceMembership.user_id).where(
            WorkspaceMembership.tenant_id == workspace.tenant_id,
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.role == WorkspaceRole.ADMIN,
        )
    )
    statuses = member_statuses(workspace.settings_json)
    active_administrator_ids = {
        user_id
        for user_id in administrator_ids
        if statuses.get(str(user_id)) != "suspended"
    }
    if member_user_id in active_administrator_ids and len(active_administrator_ids) <= 1:
        raise HTTPException(
            status_code=409,
            detail="The workspace must keep at least one active administrator",
        )


def ensure_ownership_transfer_allowed(workspace: Workspace, member_user_id: UUID) -> None:
    """A suspended member cannot become the workspace owner."""
    if is_member_suspended(workspace.settings_json, member_user_id):
        raise HTTPException(
            status_code=409,
            detail="Reactivate the member before transferring ownership",
        )
