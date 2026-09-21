from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.models import Agent, WorkspaceMembership
from northstar_api.security import Principal

from .contracts import DashboardSettings, RolesSettings, TeamsSettings
from .store import load_workspace, record_workspace_change, save_document, settings_document

router = APIRouter()
RolesManagePrincipal = Annotated[Principal, Depends(require_permissions("roles.manage"))]
TeamsManagePrincipal = Annotated[Principal, Depends(require_permissions("teams.manage"))]
BrandEditPrincipal = Annotated[Principal, Depends(require_permissions("branding.edit"))]


def _uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {label} identifier") from None


async def _validate_roles(
    payload: RolesSettings,
    principal: Principal,
    session: DBSession,
    workspace_id: UUID,
) -> None:
    role_ids = [role.id for role in payload.custom_roles]
    if len(role_ids) != len(set(role_ids)):
        raise HTTPException(status_code=422, detail="Custom role identifiers must be unique")
    known_roles = set(role_ids)
    for role in payload.custom_roles:
        if not set(role.permissions) <= set(principal.permissions):
            raise HTTPException(status_code=403, detail=f"Cannot delegate permissions not held by the current administrator ({role.name})")

    requested_users = {_uuid(user_id, "member") for user_id in payload.member_role_ids}
    if requested_users:
        available_users = set(
            await session.scalars(
                select(WorkspaceMembership.user_id).where(
                    WorkspaceMembership.tenant_id == principal.tenant_id,
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id.in_(requested_users),
                )
            )
        )
        if available_users != requested_users:
            raise HTTPException(status_code=422, detail="A custom role assignment references a member outside this workspace")
    for assigned in payload.member_role_ids.values():
        if not set(assigned) <= known_roles:
            raise HTTPException(status_code=422, detail="A custom role assignment references an unknown role")

    agent_ids: set[UUID] = set()
    for role in payload.custom_roles:
        for value in role.resources.selected.get("agents", []):
            agent_ids.add(_uuid(value, "agent resource"))
    if agent_ids:
        available_agents = set(
            await session.scalars(
                select(Agent.id).where(
                    Agent.tenant_id == principal.tenant_id,
                    Agent.workspace_id == workspace_id,
                    Agent.id.in_(agent_ids),
                    Agent.deleted_at.is_(None),
                )
            )
        )
        if available_agents != agent_ids:
            raise HTTPException(status_code=422, detail="A custom role references an agent outside this workspace")


@router.patch("/roles", response_model=RolesSettings)
async def update_roles(
    payload: RolesSettings,
    principal: RolesManagePrincipal,
    session: DBSession,
) -> RolesSettings:
    _, workspace = await load_workspace(principal, session)
    await _validate_roles(payload, principal, session, workspace.id)
    document = settings_document(workspace)
    document.roles = payload
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.roles.updated",
        [role.id for role in payload.custom_roles],
    )
    await session.commit()
    return payload


@router.patch("/teams", response_model=TeamsSettings)
async def update_teams(
    payload: TeamsSettings,
    principal: TeamsManagePrincipal,
    session: DBSession,
) -> TeamsSettings:
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    document.teams = payload
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.teams.updated",
        [team.id for team in payload.teams],
    )
    await session.commit()
    return payload


@router.patch("/dashboard", response_model=DashboardSettings)
async def update_dashboard(
    payload: DashboardSettings,
    principal: BrandEditPrincipal,
    session: DBSession,
) -> DashboardSettings:
    _, workspace = await load_workspace(principal, session)
    document = settings_document(workspace)
    document.dashboard = payload
    document.branding_draft.dashboard = payload
    save_document(workspace, document)
    record_workspace_change(
        session,
        principal,
        workspace,
        "workspace.dashboard.updated",
        [widget.id for widget in payload.widgets],
    )
    await session.commit()
    return payload
