from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import AdminPrincipal
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent

router = APIRouter(prefix="/integration-audit", tags=["integration-audit"])
DB = Annotated[AsyncSession, Depends(get_session)]


class IntegrationAuditOut(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    action: str
    entity_type: str
    entity_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


@router.get("", response_model=list[IntegrationAuditOut])
async def list_integration_audit(
    principal: AdminPrincipal,
    session: DB,
    entity_type: str | None = Query(default=None, max_length=100),
    entity_id: str | None = Query(default=None, max_length=160),
    action: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[IntegrationAuditOut]:
    query = select(IntegrationAuditEvent).where(IntegrationAuditEvent.tenant_id == principal.tenant_id)
    if entity_type:
        query = query.where(IntegrationAuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.where(IntegrationAuditEvent.entity_id == entity_id)
    if action:
        query = query.where(IntegrationAuditEvent.action == action)
    values = list(await session.scalars(query.order_by(IntegrationAuditEvent.created_at.desc()).limit(limit)))
    return [
        IntegrationAuditOut(
            id=value.id,
            actor_user_id=value.actor_user_id,
            action=value.action,
            entity_type=value.entity_type,
            entity_id=value.entity_id,
            before=value.before_json,
            after=value.after_json,
            request_id=value.request_id,
            ip_address=value.ip_address,
            user_agent=value.user_agent,
            created_at=value.created_at,
        )
        for value in values
    ]
