"""Workspace ownership independent of the immutable workspace creator.

Existing workspaces have no owner field. Resolve a legacy owner from an active
administrator (preferring the creator) without rewriting historical data.
Once explicitly assigned, never silently hand ownership to a different admin.
Ownership transfers are explicit, workspace-locked and transactional.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import (
    TenantMembership, User, Workspace, WorkspaceMembership, WorkspaceRole, WorkspaceStatus,
)
from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState
from northstar_api.services.outbox import enqueue_event

OwnershipReason = Literal["administrative_handover", "responsibility_change", "account_recovery"]


class WorkspaceOwnershipError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class WorkspaceOwner:
    user_id: UUID
    name: str


def select_owner_id(
    configured: object, creator: UUID | None, eligible: tuple[UUID, ...],
) -> UUID | None:
    """Never silently reassign a recorded owner; infer only for legacy records.

    A transferred owner may be disabled or lose tenant membership outside the
    workspace-member routes. In that case, returning the creator/another admin
    would accidentally grant ownership-transfer authority without a handover.
    Explicitly configured but invalid ownership must be recovered separately.
    """
    if not eligible:
        return None
    if configured is not None:
        try:
            stored = UUID(str(configured))
        except (TypeError, ValueError, AttributeError):
            return None
        return stored if stored in eligible else None
    if creator in eligible:
        return creator
    return eligible[0]


def eligible_member_state_filter(tenant_id: UUID, workspace_id: UUID):
    """Allow legacy members with no state row and explicitly active members only."""
    return and_(
        WorkspaceMemberState.tenant_id == tenant_id,
        WorkspaceMemberState.workspace_id == workspace_id,
        WorkspaceMemberState.user_id == User.id,
    )


async def resolve_workspace_owner(
    session: AsyncSession, *, tenant_id: UUID, workspace: Workspace,
) -> WorkspaceOwner | None:
    """Scope by tenant/workspace and exclude suspended or inactive administrators."""
    if workspace.tenant_id != tenant_id:
        return None
    rows = (await session.execute(
        select(User.id, User.name)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .outerjoin(WorkspaceMemberState, eligible_member_state_filter(tenant_id, workspace.id))
        .where(
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.role == WorkspaceRole.ADMIN,
            TenantMembership.tenant_id == tenant_id,
            User.is_active.is_(True),
            WorkspaceMemberState.suspended_at.is_(None),
        )
        .order_by(WorkspaceMembership.created_at, User.id)
    )).all()
    by_id = {user_id: name for user_id, name in rows}
    selected = select_owner_id(
        (workspace.settings_json or {}).get("ownerUserId"),
        workspace.created_by,
        tuple(by_id),
    )
    return WorkspaceOwner(selected, by_id[selected]) if selected is not None else None


async def locked_workspace(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID,
) -> Workspace:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.tenant_id == tenant_id,
            Workspace.id == workspace_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        ).with_for_update()
    )
    if workspace is None:
        raise WorkspaceOwnershipError("Workspace not found", 404)
    return workspace


async def protect_workspace_owner(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, member_user_id: UUID,
) -> None:
    """Serialize removals/demotions with transfers using the workspace lock."""
    workspace = await locked_workspace(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
    )
    owner = await resolve_workspace_owner(session, tenant_id=tenant_id, workspace=workspace)
    if owner is not None and owner.user_id == member_user_id:
        raise WorkspaceOwnershipError("Transfer workspace ownership before changing or removing this member")


async def transfer_workspace_ownership(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID,
    actor_user_id: UUID, expected_owner_user_id: UUID, target_user_id: UUID,
    reason: OwnershipReason,
) -> WorkspaceOwner:
    """Stage owner, audit and outbox changes; the caller commits or rolls back."""
    workspace = await locked_workspace(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
    )
    current = await resolve_workspace_owner(session, tenant_id=tenant_id, workspace=workspace)
    if current is None:
        raise WorkspaceOwnershipError("Workspace ownership is unavailable; recover access first")
    if current.user_id != expected_owner_user_id:
        raise WorkspaceOwnershipError("Workspace owner changed; reload before transferring")
    if current.user_id != actor_user_id:
        raise WorkspaceOwnershipError("Only the current workspace owner can transfer ownership", 403)
    if target_user_id == current.user_id:
        raise WorkspaceOwnershipError("Choose another workspace administrator")
    target = (await session.execute(
        select(User.id, User.name)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .outerjoin(WorkspaceMemberState, eligible_member_state_filter(tenant_id, workspace_id))
        .where(
            User.id == target_user_id,
            User.is_active.is_(True),
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == WorkspaceRole.ADMIN,
            TenantMembership.tenant_id == tenant_id,
            WorkspaceMemberState.suspended_at.is_(None),
        )
    )).first()
    if target is None:
        raise WorkspaceOwnershipError("Target must be an active administrator of this workspace")
    workspace.settings_json = {
        **(workspace.settings_json or {}),
        "ownerUserId": str(target_user_id),
    }
    record_audit_event(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
        actor_user_id=actor_user_id, action="workspace.owner.transferred",
        entity_type="workspace", entity_id=str(workspace_id), category="workspace",
        metadata={
            "previousOwnerUserId": str(current.user_id),
            "newOwnerUserId": str(target_user_id),
            "reasonCode": reason,
        },
    )
    event = enqueue_event(
        session, tenant_id=tenant_id, aggregate_type="workspace",
        aggregate_id=workspace_id, event_type="workspace.owner.transferred.v1",
        payload={
            "workspaceId": str(workspace_id),
            "previousOwnerUserId": str(current.user_id),
            "newOwnerUserId": str(target_user_id),
        },
    )
    event.workspace_id = workspace_id
    await session.flush()
    return WorkspaceOwner(target[0], target[1])
