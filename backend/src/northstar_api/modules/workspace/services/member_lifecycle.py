"""Workspace member suspension/reactivation with audit and outbox side effects."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import WorkspaceMembership, WorkspaceRole
from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState
from northstar_api.modules.workspace.services.admin_availability import available_workspace_admin_count
from northstar_api.modules.workspace.services.ownership import (
    WorkspaceOwnershipError,
    locked_workspace,
    protect_workspace_owner,
)
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.workspace_members import WorkspaceMemberError


async def member_statuses(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, user_ids: list[UUID],
) -> dict[UUID, str]:
    result = {user_id: "active" for user_id in user_ids}
    if not user_ids:
        return result
    states = list(await session.scalars(select(WorkspaceMemberState).where(
        WorkspaceMemberState.tenant_id == tenant_id,
        WorkspaceMemberState.workspace_id == workspace_id,
        WorkspaceMemberState.user_id.in_(user_ids),
    )))
    for state in states:
        result[state.user_id] = "suspended" if state.suspended_at is not None else "active"
    return result


async def set_member_suspended(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_user_id: UUID,
    member_user_id: UUID,
    suspended: bool,
    reason: str,
) -> bool:
    """Stage a reversible lifecycle transition in the caller's transaction.

    Lock the workspace before the target membership, as ownership transfers,
    role edits and removals do. Opposite lock ordering can deadlock two admins.
    """
    reason = reason.strip()
    if len(reason) < 3 or len(reason) > 500:
        raise WorkspaceMemberError("Provide a suspension reason between 3 and 500 characters", status_code=422)
    if actor_user_id == member_user_id:
        raise WorkspaceMemberError("You cannot suspend or reactivate your own workspace access", status_code=409)

    try:
        await locked_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
        if suspended:
            await protect_workspace_owner(
                session, tenant_id=tenant_id, workspace_id=workspace_id,
                member_user_id=member_user_id,
            )
    except WorkspaceOwnershipError as exc:
        raise WorkspaceMemberError(str(exc), status_code=exc.status_code) from None

    membership = await session.scalar(select(WorkspaceMembership).where(
        WorkspaceMembership.tenant_id == tenant_id,
        WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.user_id == member_user_id,
    ).with_for_update())
    if membership is None:
        raise WorkspaceMemberError("Workspace member not found", status_code=404)

    now = datetime.now(UTC)
    state = await session.get(WorkspaceMemberState, (workspace_id, member_user_id))
    currently_suspended = state is not None and state.suspended_at is not None
    if currently_suspended == suspended:
        return False
    if suspended and membership.role == WorkspaceRole.ADMIN:
        # The workspace lock serializes this check with other admin mutations.
        # A suspended administrator or disabled account cannot be the fallback.
        if await available_workspace_admin_count(
            session, tenant_id=tenant_id, workspace_id=workspace_id,
        ) <= 1:
            raise WorkspaceMemberError(
                "The workspace must keep at least one active administrator",
                status_code=409,
            )
    if state is None:
        state = WorkspaceMemberState(
            tenant_id=tenant_id, workspace_id=workspace_id, user_id=member_user_id,
            suspended_at=now if suspended else None, created_at=now, updated_at=now,
        )
        session.add(state)
    else:
        state.suspended_at = now if suspended else None
        state.updated_at = now

    action = "workspace.member.suspended" if suspended else "workspace.member.reactivated"
    event_type = "workspace.member.suspended.v1" if suspended else "workspace.member.reactivated.v1"
    record_audit_event(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type="workspace_member",
        entity_id=str(member_user_id),
        category="access",
        metadata={"reason": reason},
    )
    event = enqueue_event(
        session,
        tenant_id=tenant_id,
        aggregate_type="workspace_member",
        aggregate_id=member_user_id,
        event_type=event_type,
        payload={"workspaceId": str(workspace_id), "userId": str(member_user_id)},
    )
    event.workspace_id = workspace_id
    await session.flush()
    return True
