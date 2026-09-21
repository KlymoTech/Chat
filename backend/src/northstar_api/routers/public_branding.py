from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select, text

from northstar_api.database import set_tenant_context
from northstar_api.dependencies import DBSession
from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.modules.workspace.store import settings_document
from northstar_api.onboarding_contract import SetupContract

router = APIRouter(prefix="/branding", tags=["public-branding"])


class PublicBrandingResponse(SetupContract):
    workspace_id: UUID
    company_name: str
    browser_title: str
    logo_data_url: str
    favicon_data_url: str
    primary_color: str
    secondary_color: str
    colors: dict[str, str]
    typography: dict[str, str | int | float]
    authentication: dict[str, Any]
    support_url: str


def _hostname(value: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if not normalized or len(normalized) > 253 or "://" in normalized or "/" in normalized or " " in normalized:
        raise HTTPException(status_code=400, detail="Invalid hostname")
    return normalized


async def _resolve_workspace(session: DBSession, hostname: str) -> Workspace | None:
    if session.bind and session.bind.dialect.name == "postgresql":
        row = (
            await session.execute(
                text(
                    "SELECT tenant_id, workspace_id "
                    "FROM northstar_resolve_workspace_domain(:hostname)"
                ),
                {"hostname": hostname},
            )
        ).mappings().first()
        if row is None:
            return None
        await set_tenant_context(session, UUID(str(row["tenant_id"])))
        return await session.scalar(
            select(Workspace).where(
                Workspace.id == UUID(str(row["workspace_id"])),
                Workspace.tenant_id == UUID(str(row["tenant_id"])),
                Workspace.status == WorkspaceStatus.ACTIVE,
            )
        )

    workspaces = await session.scalars(select(Workspace).where(Workspace.status == WorkspaceStatus.ACTIVE))
    for workspace in workspaces:
        document = settings_document(workspace)
        if any(item.hostname == hostname and item.status == "active" for item in document.domains.domains):
            return workspace
    return None


@router.get("/health", status_code=204)
async def branding_health() -> Response:
    return Response(status_code=204)


@router.get("/public", response_model=PublicBrandingResponse)
async def public_branding(
    session: DBSession,
    hostname: str = Query(min_length=4, max_length=253),
) -> PublicBrandingResponse:
    workspace = await _resolve_workspace(session, _hostname(hostname))
    if workspace is None:
        raise HTTPException(status_code=404, detail="No active brand is configured for this domain")
    published = settings_document(workspace).branding_published
    if published is None or not published.identity.branded_login:
        raise HTTPException(status_code=404, detail="No active login brand is configured for this domain")
    identity = published.identity
    return PublicBrandingResponse(
        workspace_id=workspace.id,
        company_name=identity.company_name,
        browser_title=identity.browser_title,
        logo_data_url=identity.logo_data_url,
        favicon_data_url=identity.favicon_data_url,
        primary_color=identity.primary_color,
        secondary_color=identity.secondary_color,
        colors=published.colors,
        typography=published.typography,
        authentication=published.authentication.model_dump(by_alias=True, mode="json"),
        support_url=identity.support_url,
    )
