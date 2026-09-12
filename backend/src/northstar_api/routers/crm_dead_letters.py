from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.dead_letter_schemas import CRMDeadLetterOut
from northstar_api.lead_crm.models import CRMDelivery, IntegrationDeadLetter
from northstar_api.models import Lead
from northstar_api.security import Principal

router = APIRouter(prefix="/crm/dead-letters", tags=["crm"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMViewPrincipal = Annotated[Principal, Depends(require_permissions("crm.view"))]
DeadLetterStatus = Literal["open", "resolved", "all"]


@router.get("", response_model=list[CRMDeadLetterOut])
async def list_crm_dead_letters(
    principal: CRMViewPrincipal,
    session: DB,
    connection_id: UUID | None = Query(default=None),
    dead_letter_status: DeadLetterStatus = Query(default="open", alias="status"),
) -> list[CRMDeadLetterOut]:
    """List dead letters that resolve through a Lead in the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    conditions = [
        IntegrationDeadLetter.tenant_id == principal.tenant_id,
        CRMDelivery.tenant_id == principal.tenant_id,
        Lead.tenant_id == principal.tenant_id,
        Lead.workspace_id == principal.workspace_id,
    ]
    if connection_id is not None:
        conditions.append(CRMDelivery.connection_id == connection_id)
    if dead_letter_status != "all":
        conditions.append(IntegrationDeadLetter.status == dead_letter_status)

    rows = list(
        await session.execute(
            select(IntegrationDeadLetter, CRMDelivery)
            .join(CRMDelivery, CRMDelivery.id == IntegrationDeadLetter.delivery_id)
            .join(Lead, Lead.id == CRMDelivery.lead_id)
            .where(*conditions)
            .order_by(IntegrationDeadLetter.created_at.desc())
            .limit(200)
        )
    )
    return [
        CRMDeadLetterOut(
            id=dead_letter.id,
            delivery_id=delivery.id,
            lead_id=delivery.lead_id,
            connection_id=delivery.connection_id,
            provider=delivery.provider,
            status=dead_letter.status,
            reason_code=dead_letter.reason_code,
            reason_message=dead_letter.reason_message,
            created_at=dead_letter.created_at,
            updated_at=dead_letter.updated_at,
            resolved_at=dead_letter.resolved_at,
        )
        for dead_letter, delivery in rows
    ]
