"""Authoritative tenant-scoped count of administrators able to access a workspace.

Used by member lifecycle and last-admin protections. An admin whose account is
disabled or whose workspace membership is suspended cannot be the only fallback
when changing another administrator's access.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import TenantMembership, User, WorkspaceMembership, WorkspaceRole
from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState


async def available_workspace_admin_count(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID,
    exclude_user_id: UUID | None = None,
) -> int:
    """Count usable admins, optionally excluding an admin being removed or demoted."""
    suspended = select(WorkspaceMemberState.user_id).where(
        WorkspaceMemberState.tenant_id == tenant_id,
        WorkspaceMemberState.workspace_id == workspace_id,
        WorkspaceMemberState.user_id == WorkspaceMembership.user_id,
        WorkspaceMemberState.suspended_at.is_not(None),
    ).exists()
    statement = (
        select(func.count())
        .select_from(WorkspaceMembership)
        .join(User, User.id == WorkspaceMembership.user_id)
        .join(
            TenantMembership,
            (TenantMembership.user_id == WorkspaceMembership.user_id)
            & (TenantMembership.tenant_id == tenant_id),
        )
        .where(
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == WorkspaceRole.ADMIN,
            User.is_active.is_(True),
            ~suspended,
        )
    )
    if exclude_user_id is not None:
        statement = statement.where(WorkspaceMembership.user_id != exclude_user_id)
    count = await session.scalar(statement)
    return int(count or 0)
