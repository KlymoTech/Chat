from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.security import Principal

from .contracts import DashboardSettings, RolesSettings, TeamsSettings
from .store import load_workspace, record_workspace_change, save_document, settings_document

router = APIRouter()
RolesManagePrincipal = Annotated[Principal, Depends(require_permissions("roles.manage"))]
TeamsManagePrincipal = Annotated[Principal, Depends(require_permissions("teams.manage"))]
BrandEditPrincipal = Annotated[Principal, Depends(require_permissions("branding.edit"))]


@router.patch("/roles", response_model=RolesSettings)
async def update_roles(
    payload: RolesSettings,
    principal: RolesManagePrincipal,
    session: DBSession,
) -> RolesSettings:
    _, workspace = await load_workspace(principal, session)
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
