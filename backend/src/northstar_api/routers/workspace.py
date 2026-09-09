from __future__ import annotations

import re
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr, Field, field_validator
from sqlalchemy import func, select

from northstar_api.dependencies import CurrentPrincipal, DBSession, require_permissions
from northstar_api.models import (
    Role,
    Tenant,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
    WorkspaceStatus,
)
from northstar_api.schemas import APIModel
from northstar_api.security import Principal, WORKSPACE_ROLE_PERMISSIONS

router = APIRouter(prefix="/workspace", tags=["workspace"])
collection_router = APIRouter(prefix="/workspaces", tags=["workspaces"])
WorkspaceViewPrincipal = Annotated[Principal, Depends(require_permissions("workspace.view"))]
WorkspaceUpdatePrincipal = Annotated[Principal, Depends(require_permissions("workspace.update"))]


class WorkspacePreferences(APIModel):
    timezone: str = Field(default="Asia/Calcutta", min_length=2, max_length=80)
    default_language: str = Field(default="English", min_length=2, max_length=60)
    date_format: Literal["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] = "DD/MM/YYYY"


class WhiteLabelSettings(APIModel):
    company_name: str = Field(default="Northstar AI", min_length=2, max_length=120)
    logo_data_url: str = Field(default="", max_length=500_000)
    favicon_data_url: str = Field(default="", max_length=500_000)
    app_icon_data_url: str = Field(default="", max_length=500_000)
    primary_color: str = "#146cf6"
    secondary_color: str = "#705cf6"
    support_email: EmailStr | None = None
    support_url: str = Field(default="", max_length=2000)
    browser_title: str = Field(default="Northstar AI", min_length=1, max_length=120)
    custom_domain: str = Field(default="", max_length=253)
    dns_status: Literal["not-configured", "pending", "verified"] = "not-configured"
    branded_login: bool = True
    branded_dashboard: bool = True
    branded_widget: bool = True
    branded_emails: bool = True
    remove_platform_branding: bool = False

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def valid_color(cls, value: str) -> str:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("must be a six-digit hex color")
        return value.lower()

    @field_validator("logo_data_url", "favicon_data_url", "app_icon_data_url")
    @classmethod
    def safe_image(cls, value: str) -> str:
        if value and not re.match(r"^data:image/(png|jpeg|webp|svg\+xml);base64,", value):
            raise ValueError("must be a supported image data URL")
        return value

    @field_validator("custom_domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        normalized = value.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
        if normalized and ("/" in normalized or " " in normalized or "." not in normalized):
            raise ValueError("must be a valid hostname")
        return normalized


class WorkspaceOut(APIModel):
    id: str
    tenant_id: str
    tenant_name: str
    name: str
    slug: str
    status: WorkspaceStatus
    role: WorkspaceRole
    permissions: list[str]
    plan: str
    member_count: int
    preferences: WorkspacePreferences
    white_label: WhiteLabelSettings


class WorkspacePatch(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    slug: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    preferences: WorkspacePreferences | None = None
    white_label: WhiteLabelSettings | None = None


class WorkspaceCreate(APIModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    timezone: str = Field(default="Asia/Calcutta", min_length=2, max_length=80)
    default_language: str = Field(default="English", min_length=2, max_length=60)
    date_format: Literal["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] = "DD/MM/YYYY"


def _workspace_response(
    tenant: Tenant,
    workspace: Workspace,
    membership: WorkspaceMembership,
    member_count: int,
) -> WorkspaceOut:
    settings: dict[str, Any] = workspace.settings_json or {}
    return WorkspaceOut(
        id=str(workspace.id),
        tenant_id=str(tenant.id),
        tenant_name=tenant.name,
        name=workspace.name,
        slug=workspace.slug,
        status=workspace.status,
        role=membership.role,
        permissions=sorted(WORKSPACE_ROLE_PERMISSIONS[membership.role]),
        plan=tenant.plan,
        member_count=member_count,
        preferences=WorkspacePreferences.model_validate({
            "timezone": workspace.timezone,
            "defaultLanguage": workspace.default_language,
            "dateFormat": workspace.date_format,
            **settings.get("preferences", {}),
        }),
        white_label=WhiteLabelSettings.model_validate(
            {"companyName": tenant.name, **(workspace.branding_json or {})}
        ),
    )


async def _load_workspace(
    tenant_id: Any,
    workspace_id: UUID | None,
    user_id: UUID,
    session: DBSession,
) -> tuple[Tenant, Workspace, WorkspaceMembership, int]:
    result = await session.execute(
        select(Tenant, Workspace, WorkspaceMembership)
        .join(Workspace, Workspace.tenant_id == Tenant.id)
        .join(
            WorkspaceMembership,
            WorkspaceMembership.workspace_id == Workspace.id,
        )
        .where(
            Tenant.id == tenant_id,
            Workspace.id == workspace_id,
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.tenant_id == tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    member_count = int(
        await session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
        )
        or 0
    )
    tenant, workspace, membership = row
    return tenant, workspace, membership, member_count


@router.get("", response_model=WorkspaceOut)
async def get_workspace(principal: WorkspaceViewPrincipal, session: DBSession) -> WorkspaceOut:
    tenant, workspace, membership, member_count = await _load_workspace(
        principal.tenant_id, principal.workspace_id, principal.user_id, session
    )
    return _workspace_response(tenant, workspace, membership, member_count)


@router.patch("", response_model=WorkspaceOut)
async def update_workspace(
    payload: WorkspacePatch,
    principal: WorkspaceUpdatePrincipal,
    session: DBSession,
) -> WorkspaceOut:
    tenant, workspace, membership, member_count = await _load_workspace(
        principal.tenant_id, principal.workspace_id, principal.user_id, session
    )
    if payload.slug and payload.slug != workspace.slug:
        duplicate = await session.scalar(
            select(Workspace.id).where(
                Workspace.tenant_id == principal.tenant_id,
                Workspace.slug == payload.slug,
                Workspace.id != workspace.id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Workspace slug is already in use")
        workspace.slug = payload.slug
    if payload.name is not None:
        workspace.name = payload.name.strip()

    settings = dict(workspace.settings_json or {})
    if payload.preferences is not None:
        settings["preferences"] = payload.preferences.model_dump(by_alias=True)
        workspace.timezone = payload.preferences.timezone
        workspace.default_language = payload.preferences.default_language
        workspace.date_format = payload.preferences.date_format
    if payload.white_label is not None:
        workspace.branding_json = payload.white_label.model_dump(by_alias=True, mode="json")
    workspace.settings_json = settings
    await session.commit()
    await session.refresh(workspace)
    return _workspace_response(tenant, workspace, membership, member_count)


@collection_router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(principal: WorkspaceViewPrincipal, session: DBSession) -> list[WorkspaceOut]:
    rows = (
        await session.execute(
            select(Tenant, Workspace, WorkspaceMembership)
            .join(Workspace, Workspace.tenant_id == Tenant.id)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(
                Tenant.id == principal.tenant_id,
                WorkspaceMembership.user_id == principal.user_id,
                WorkspaceMembership.tenant_id == principal.tenant_id,
                Workspace.status == WorkspaceStatus.ACTIVE,
            )
            .order_by(Workspace.name, Workspace.id)
        )
    ).all()
    results: list[WorkspaceOut] = []
    for tenant, workspace, membership in rows:
        member_count = int(
            await session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(WorkspaceMembership.workspace_id == workspace.id)
            )
            or 0
        )
        results.append(_workspace_response(tenant, workspace, membership, member_count))
    return results


@collection_router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    principal: CurrentPrincipal,
    session: DBSession,
) -> WorkspaceOut:
    if principal.role not in {Role.OWNER, Role.ADMIN}:
        raise HTTPException(status_code=403, detail="Only a tenant owner or admin can create workspaces")
    duplicate = await session.scalar(
        select(Workspace.id).where(
            Workspace.tenant_id == principal.tenant_id,
            Workspace.slug == payload.slug,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Workspace slug is already in use")
    tenant = await session.scalar(select(Tenant).where(Tenant.id == principal.tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    workspace = Workspace(
        tenant_id=principal.tenant_id,
        name=payload.name.strip(),
        slug=payload.slug,
        timezone=payload.timezone,
        default_language=payload.default_language,
        date_format=payload.date_format,
        created_by=principal.user_id,
    )
    session.add(workspace)
    await session.flush()
    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        role=WorkspaceRole.ADMIN,
        all_agents_access=True,
    )
    session.add(membership)
    await session.commit()
    await session.refresh(workspace)
    return _workspace_response(tenant, workspace, membership, 1)


@collection_router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace_by_id(
    workspace_id: UUID,
    principal: WorkspaceViewPrincipal,
    session: DBSession,
) -> WorkspaceOut:
    tenant, workspace, membership, member_count = await _load_workspace(
        principal.tenant_id, workspace_id, principal.user_id, session
    )
    return _workspace_response(tenant, workspace, membership, member_count)
