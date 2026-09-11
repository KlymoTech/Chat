from __future__ import annotations

import json
import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from northstar_api.dependencies import CurrentPrincipal, DBSession
from northstar_api.models import User
from northstar_api.platform_admin_schemas import (
    PlatformAdminAccessOut,
    PlatformOverviewOut,
    PlatformTenantDetailOut,
    PlatformTenantListOut,
)
from northstar_api.security import Principal
from northstar_api.services.platform_admin import (
    get_platform_tenant,
    list_platform_tenants,
    platform_overview,
)

router = APIRouter(prefix="/platform-admin", tags=["platform admin"])


def platform_admin_emails(raw: str | None = None) -> frozenset[str]:
    value = os.getenv("PLATFORM_ADMIN_EMAILS", "") if raw is None else raw
    normalized = value.strip()
    if not normalized:
        return frozenset()
    values: list[object]
    if normalized.startswith("["):
        try:
            decoded = json.loads(normalized)
        except json.JSONDecodeError:
            decoded = []
        values = decoded if isinstance(decoded, list) else []
    else:
        values = normalized.split(",")
    return frozenset(
        str(item).strip().lower()
        for item in values
        if str(item).strip()
    )


async def require_platform_admin(
    principal: CurrentPrincipal,
    session: DBSession,
) -> Principal:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot access the platform control plane",
        )
    allowed = platform_admin_emails()
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administration is not enabled for this account",
        )
    email = await session.scalar(
        select(User.email).where(
            User.id == principal.user_id,
            User.is_active.is_(True),
        )
    )
    if email is None or email.strip().lower() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator access required",
        )
    return principal


PlatformAdminPrincipal = Annotated[Principal, Depends(require_platform_admin)]


async def _platform_admin_email(session: DBSession, principal: Principal) -> str:
    value = await session.scalar(select(User.email).where(User.id == principal.user_id))
    if value is None:
        raise HTTPException(status_code=401, detail="Account is unavailable")
    return value


@router.get("/access", response_model=PlatformAdminAccessOut)
async def get_platform_admin_access(
    principal: PlatformAdminPrincipal,
    session: DBSession,
) -> PlatformAdminAccessOut:
    return PlatformAdminAccessOut(
        authorized=True,
        email=await _platform_admin_email(session, principal),
    )


@router.get("/overview", response_model=PlatformOverviewOut)
async def get_platform_overview(
    _: PlatformAdminPrincipal,
    session: DBSession,
) -> PlatformOverviewOut:
    return await platform_overview(session)


@router.get("/tenants", response_model=PlatformTenantListOut)
async def get_platform_tenants(
    _: PlatformAdminPrincipal,
    session: DBSession,
    search: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PlatformTenantListOut:
    return await list_platform_tenants(
        session,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/tenants/{tenant_id}", response_model=PlatformTenantDetailOut)
async def get_platform_tenant_detail(
    tenant_id: UUID,
    _: PlatformAdminPrincipal,
    session: DBSession,
) -> PlatformTenantDetailOut:
    value = await get_platform_tenant(session, tenant_id=tenant_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return value
