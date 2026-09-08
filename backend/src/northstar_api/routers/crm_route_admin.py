from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import AdminPrincipal
from northstar_api.lead_crm.api_schemas import CRMRouteOut
from northstar_api.lead_crm.models import CRMConnection, CRMRoute

router = APIRouter(tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]


class CRMRoutePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    conditions: dict[str, Any] | None = None
    connection_ids: list[UUID] | None = None


def _route_out(value: CRMRoute) -> CRMRouteOut:
    actions = dict(value.actions_json or {})
    raw_connection_ids = actions.get("connectionIds")
    connection_ids = [str(item) for item in raw_connection_ids] if isinstance(raw_connection_ids, list) else []
    return CRMRouteOut(
        id=value.id,
        name=value.name,
        enabled=value.enabled,
        priority=value.priority,
        version=value.version,
        conditions=dict(value.conditions_json or {}),
        connection_ids=connection_ids,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


async def _assert_connections_owned(
    session: AsyncSession, *, tenant_id: UUID, connection_ids: list[UUID]
) -> None:
    if not connection_ids:
        return
    owned = set(
        await session.scalars(
            select(CRMConnection.id).where(
                CRMConnection.tenant_id == tenant_id,
                CRMConnection.id.in_(connection_ids),
            )
        )
    )
    if owned != set(connection_ids):
        raise HTTPException(
            status_code=400,
            detail="Route references a CRM connection outside this workspace",
        )


@router.patch("/crm/routes/{route_id}", response_model=CRMRouteOut)
async def patch_crm_route(
    route_id: UUID,
    payload: CRMRoutePatch,
    principal: AdminPrincipal,
    session: DB,
) -> CRMRouteOut:
    value = await session.scalar(
        select(CRMRoute).where(
            CRMRoute.id == route_id,
            CRMRoute.tenant_id == principal.tenant_id,
        )
    )
    if value is None:
        raise HTTPException(status_code=404, detail="CRM route not found")
    if payload.connection_ids is not None:
        await _assert_connections_owned(
            session,
            tenant_id=principal.tenant_id,
            connection_ids=payload.connection_ids,
        )
        value.actions_json = {"connectionIds": [str(item) for item in payload.connection_ids]}
    if payload.name is not None:
        value.name = payload.name
    if payload.enabled is not None:
        value.enabled = payload.enabled
    if payload.priority is not None:
        value.priority = payload.priority
    if payload.conditions is not None:
        value.conditions_json = payload.conditions
    value.version += 1
    await session.commit()
    await session.refresh(value)
    return _route_out(value)


@router.delete("/crm/routes/{route_id}", status_code=204)
async def delete_crm_route(
    route_id: UUID,
    principal: AdminPrincipal,
    session: DB,
) -> None:
    value = await session.scalar(
        select(CRMRoute).where(
            CRMRoute.id == route_id,
            CRMRoute.tenant_id == principal.tenant_id,
        )
    )
    if value is None:
        raise HTTPException(status_code=404, detail="CRM route not found")
    await session.delete(value)
    await session.commit()
