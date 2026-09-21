from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.models import (
    Agent,
    Role,
    TenantMembership,
    User,
    Workspace,
    WorkspaceMemberAgentAccess,
    WorkspaceMembership,
    WorkspaceRole,
)
from northstar_api.modules.workspace.models.member_state import WorkspaceMemberState
from northstar_api.modules.workspace.services.ownership import WorkspaceOwnershipError, protect_workspace_owner
from northstar_api.services.outbox import enqueue_event


class WorkspaceMemberError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class WorkspaceMemberDetails:
    membership: WorkspaceMembership
    user: User
    agent_ids: tuple[UUID, ...]


async def validate_agent_scope(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    all_agents_access: bool,
    agent_ids: list[UUID],
) -> tuple[UUID, ...]:
    if all_agents_access:
        if agent_ids:
            raise WorkspaceMemberError(
                "Agent restrictions cannot be supplied when all-agent access is enabled",
                status_code=422,
            )
        return ()
    unique_ids = tuple(dict.fromkeys(agent_ids))
    if not unique_ids:
        return ()
    available = set(
        await session.scalars(
            select(Agent.id).where(
                Agent.tenant_id == tenant_id,
                Agent.workspace_id == workspace_id,
                Agent.id.in_(unique_ids),
                Agent.deleted_at.is_(None),
            )
        )
    )
    if available != set(unique_ids):
        raise WorkspaceMemberError(
            "One or more selected agents are unavailable in this workspace",
            status_code=422,
        )
    return unique_ids


async def replace_member_agent_access(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    agent_ids: tuple[UUID, ...],
) -> None:
    await session.execute(
        delete(WorkspaceMemberAgentAccess).where(
            WorkspaceMemberAgentAccess.workspace_id == workspace_id,
            WorkspaceMemberAgentAccess.user_id == user_id,
        )
    )
    session.add_all(
        [
            WorkspaceMemberAgentAccess(
                workspace_id=workspace_id,
                user_id=user_id,
                agent_id=agent_id,
            )
            for agent_id in agent_ids
        ]
    )


async def list_workspace_members(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
) -> list[WorkspaceMemberDetails]:
    rows = (
        await session.execute(
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.tenant_id == tenant_id,
                WorkspaceMembership.workspace_id == workspace_id,
                User.is_active.is_(True),
            )
            .order_by(WorkspaceMembership.created_at, User.email)
        )
    ).all()
    user_ids = [membership.user_id for membership, _ in rows]
    access: dict[UUID, list[UUID]] = {user_id: [] for user_id in user_ids}
    if user_ids:
        entries = (
            await session.execute(
                select(
                    WorkspaceMemberAgentAccess.user_id,
                    WorkspaceMemberAgentAccess.agent_id,
                )
                .where(
                    WorkspaceMemberAgentAccess.workspace_id == workspace_id,
                    WorkspaceMemberAgentAccess.user_id.in_(user_ids),
                )
                .order_by(
                    WorkspaceMemberAgentAccess.user_id,
                    WorkspaceMemberAgentAccess.agent_id,
                )
            )
        ).all()
        for user_id, agent_id in entries:
            access.setdefault(user_id, []).append(agent_id)
    return [
        WorkspaceMemberDetails(
            membership=membership,
            user=user,
            agent_ids=tuple(access.get(membership.user_id, [])),
        )
        for membership, user in rows
    ]


async def _require_other_member(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_user_id: UUID,
    member_user_id: UUID,
) -> tuple[WorkspaceMembership, User]:
    if actor_user_id == member_user_id:
        raise WorkspaceMemberError(
            "Use another workspace administrator to change your own access",
            status_code=409,
        )
    row = (
        await session.execute(
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(
                WorkspaceMembership.tenant_id == tenant_id,
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == member_user_id,
            )
            .with_for_update()
        )
    ).first()
    if row is None:
        raise WorkspaceMemberError("Workspace member not found", status_code=404)
    return row


async def _protect_last_admin(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    membership: WorkspaceMembership,
    next_role: WorkspaceRole | None,
) -> None:
    removing_admin = membership.role == WorkspaceRole.ADMIN and next_role != WorkspaceRole.ADMIN
    if not removing_admin:
        return

    workspace = await session.scalar(
        select(Workspace.id).where(Workspace.id == workspace_id).with_for_update()
    )
    if workspace is None:
        raise WorkspaceMemberError("Workspace not found", status_code=404)

    count = int(
        await session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == WorkspaceRole.ADMIN,
            )
        )
        or 0
    )
    if count <= 1:
        raise WorkspaceMemberError(
            "The workspace must keep at least one administrator",
            status_code=409,
        )


async def _protect_current_owner(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, member_user_id: UUID,
) -> None:
    try:
        await protect_workspace_owner(
            session, tenant_id=tenant_id, workspace_id=workspace_id,
            member_user_id=member_user_id,
        )
    except WorkspaceOwnershipError as exc:
        raise WorkspaceMemberError(str(exc), status_code=exc.status_code) from None


def _stage_member_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_user_id: UUID,
    member_user_id: UUID,
    action: str,
    event_type: str,
    fields: list[str] | None = None,
) -> None:
    metadata = {"fields": fields} if fields else None
    record_audit_event(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type="workspace_member",
        entity_id=str(member_user_id),
        category="access",
        metadata=metadata,
    )
    payload: dict[str, object] = {
        "workspaceId": str(workspace_id),
        "userId": str(member_user_id),
    }
    if fields:
        payload["fields"] = fields
    event = enqueue_event(
        session,
        tenant_id=tenant_id,
        aggregate_type="workspace_member",
        aggregate_id=member_user_id,
        event_type=event_type,
        payload=payload,
    )
    event.workspace_id = workspace_id


async def update_workspace_member(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_user_id: UUID,
    member_user_id: UUID,
    role: WorkspaceRole,
    all_agents_access: bool,
    agent_ids: list[UUID],
) -> WorkspaceMemberDetails:
    await _protect_current_owner(
        session, tenant_id=tenant_id, workspace_id=workspace_id, member_user_id=member_user_id,
    )
    membership, user = await _require_other_member(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        member_user_id=member_user_id,
    )
    await _protect_last_admin(
        session,
        workspace_id=workspace_id,
        membership=membership,
        next_role=role,
    )
    selected = await validate_agent_scope(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        all_agents_access=all_agents_access,
        agent_ids=agent_ids,
    )
    previous_agent_ids = tuple(await session.scalars(select(WorkspaceMemberAgentAccess.agent_id).where(
        WorkspaceMemberAgentAccess.workspace_id == workspace_id,
        WorkspaceMemberAgentAccess.user_id == member_user_id,
    ).order_by(WorkspaceMemberAgentAccess.agent_id)))
    changed_fields: list[str] = []
    if membership.role != role:
        changed_fields.append("role")
    if membership.all_agents_access != all_agents_access:
        changed_fields.append("all_agents_access")
    if previous_agent_ids != tuple(sorted(selected)):
        changed_fields.append("agent_ids")

    membership.role = role
    membership.all_agents_access = all_agents_access
    membership.updated_at = datetime.now(UTC)
    await replace_member_agent_access(
        session,
        workspace_id=workspace_id,
        user_id=member_user_id,
        agent_ids=selected,
    )
    if changed_fields:
        _stage_member_event(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            member_user_id=member_user_id,
            action="workspace.member.updated",
            event_type="workspace.member.updated.v1",
            fields=changed_fields,
        )
    await session.flush()
    return WorkspaceMemberDetails(membership=membership, user=user, agent_ids=selected)


async def remove_workspace_member(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    actor_user_id: UUID,
    member_user_id: UUID,
) -> None:
    await _protect_current_owner(
        session, tenant_id=tenant_id, workspace_id=workspace_id, member_user_id=member_user_id,
    )
    membership, _ = await _require_other_member(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        member_user_id=member_user_id,
    )
    await _protect_last_admin(
        session,
        workspace_id=workspace_id,
        membership=membership,
        next_role=None,
    )
    await session.execute(
        delete(WorkspaceMemberAgentAccess).where(
            WorkspaceMemberAgentAccess.workspace_id == workspace_id,
            WorkspaceMemberAgentAccess.user_id == member_user_id,
        )
    )
    await session.execute(
        delete(WorkspaceMemberState).where(
            WorkspaceMemberState.tenant_id == tenant_id,
            WorkspaceMemberState.workspace_id == workspace_id,
            WorkspaceMemberState.user_id == member_user_id,
        )
    )
    _stage_member_event(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        member_user_id=member_user_id,
        action="workspace.member.removed",
        event_type="workspace.member.removed.v1",
    )
    await session.delete(membership)
    remaining = await session.scalar(
        select(WorkspaceMembership.workspace_id).where(
            WorkspaceMembership.tenant_id == tenant_id,
            WorkspaceMembership.user_id == member_user_id,
            WorkspaceMembership.workspace_id != workspace_id,
        )
    )
    if remaining is None:
        tenant_membership = await session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == member_user_id,
            )
        )
        if tenant_membership is not None and tenant_membership.role in {
            Role.MEMBER,
            Role.ANALYST,
        }:
            await session.delete(tenant_membership)
    await session.flush()
