"""Explicit, organization-owner-authorized recovery of unavailable Workspace ownership.

Do not infer an owner from a disabled/suspended recorded owner. Recovery is a
separate administrative operation, serialised with transfers and member changes
by the existing workspace row lock. The caller owns the transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import (
    Role, TenantMembership, User, WorkspaceMembership, WorkspaceRole,
)
from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState
from northstar_api.modules.workspace.services.ownership import (
    WorkspaceOwner, WorkspaceOwnershipError, eligible_member_state_filter,
    locked_workspace, resolve_workspace_owner,
)
from northstar_api.services.outbox import enqueue_event

RecoveryReason = Literal["recorded_owner_unavailable", "legacy_owner_unavailable"]


@dataclass(frozen=True, slots=True)
class WorkspaceRecoveryResult:
    owner: WorkspaceOwner
    creator_user_id: UUID | None


async def recover_workspace_ownership(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID,
    actor_user_id: UUID, target_user_id: UUID, reason: RecoveryReason,
) -> WorkspaceRecoveryResult:
    """Stage an explicit recovery without silently changing any user roles.

    Authorization is checked again against the database, not only against a
    potentially stale JWT or a frontend control. A different eligible admin is
    required so an organization owner cannot appoint themself in recovery.
    """
    if actor_user_id == target_user_id:
        raise WorkspaceOwnershipError(
            "Choose a different active workspace administrator for recovery", 409,
        )
    workspace = await locked_workspace(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
    )
    authority = await session.scalar(
        select(TenantMembership.user_id)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == actor_user_id,
            TenantMembership.role == Role.OWNER,
            User.is_active.is_(True),
        )
    )
    if authority is None:
        raise WorkspaceOwnershipError("Only an active organization owner can recover workspace ownership", 403)
    if await resolve_workspace_owner(session, tenant_id=tenant_id, workspace=workspace) is not None:
        raise WorkspaceOwnershipError("Workspace already has an active owner; use ownership transfer", 409)

    configured = (workspace.settings_json or {}).get("ownerUserId")
    if reason == "recorded_owner_unavailable" and configured is None:
        raise WorkspaceOwnershipError("Select the reason for a legacy workspace without an owner", 422)
    if reason == "legacy_owner_unavailable" and configured is not None:
        raise WorkspaceOwnershipError("Select the reason for an unavailable recorded owner", 422)

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
        raise WorkspaceOwnershipError("Target must be an active, unsuspended administrator of this workspace", 409)

    workspace.settings_json = {**(workspace.settings_json or {}), "ownerUserId": str(target_user_id)}
    metadata = {
        "recoveredOwnerUserId": str(target_user_id),
        "reasonCode": reason,
        "hadRecordedOwner": configured is not None,
    }
    record_audit_event(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
        actor_user_id=actor_user_id, action="workspace.owner.recovered",
        entity_type="workspace", entity_id=str(workspace_id), category="security",
        metadata=metadata,
    )
    event = enqueue_event(
        session, tenant_id=tenant_id, aggregate_type="workspace",
        aggregate_id=workspace_id, event_type="workspace.owner.recovered.v1",
        payload={"workspaceId": str(workspace_id), **metadata},
    )
    event.workspace_id = workspace_id
    await session.flush()
    return WorkspaceRecoveryResult(
        owner=WorkspaceOwner(target[0], target[1]),
        creator_user_id=workspace.created_by,
    )
