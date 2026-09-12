from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.channel_webhook_event_schemas import ChannelWebhookEventOut
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.security import Principal

router = APIRouter(prefix="/channels/webhook-events", tags=["channels"])
DB = Annotated[AsyncSession, Depends(get_session)]
ChannelsViewPrincipal = Annotated[Principal, Depends(require_permissions("integrations.view"))]


def _error_code(processing_status: str) -> str | None:
    if processing_status == "failed":
        return "processing_failed"
    if processing_status == "rejected":
        return "processing_rejected"
    return None


def _out(value: RawWebhookEvent) -> ChannelWebhookEventOut:
    return ChannelWebhookEventOut(
        id=value.id,
        connection_id=UUID(value.connection_key),
        provider=value.provider,
        event_type=value.event_type,
        verification_status=value.verification_status,
        processing_status=value.processing_status,
        attempt_count=value.attempt_count,
        error_code=_error_code(value.processing_status),
        correlation_id=value.correlation_id,
        received_at=value.received_at,
        processed_at=value.processed_at,
    )


@router.get("", response_model=list[ChannelWebhookEventOut])
async def list_channel_webhook_events(
    principal: ChannelsViewPrincipal,
    session: DB,
    connection_id: UUID | None = Query(default=None),
    processing_status: str | None = Query(default=None, max_length=40),
    provider: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ChannelWebhookEventOut]:
    """List safe inbound webhook processing evidence for the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    connection_query = (
        select(ChannelConnection.id)
        .join(
            WorkspaceChannelConnection,
            WorkspaceChannelConnection.connection_id == ChannelConnection.id,
        )
        .where(
            ChannelConnection.tenant_id == principal.tenant_id,
            WorkspaceChannelConnection.tenant_id == principal.tenant_id,
            WorkspaceChannelConnection.workspace_id == principal.workspace_id,
        )
    )
    if connection_id is not None:
        connection_query = connection_query.where(ChannelConnection.id == connection_id)

    connection_ids = list(await session.scalars(connection_query))
    if connection_id is not None and not connection_ids:
        raise HTTPException(status_code=404, detail="Channel connection not found in this workspace")
    if not connection_ids:
        return []

    query = select(RawWebhookEvent).where(
        RawWebhookEvent.tenant_id == principal.tenant_id,
        RawWebhookEvent.connection_key.in_([str(value) for value in connection_ids]),
    )
    if processing_status:
        query = query.where(RawWebhookEvent.processing_status == processing_status)
    if provider:
        query = query.where(RawWebhookEvent.provider == provider)

    values = list(
        await session.scalars(
            query.order_by(RawWebhookEvent.received_at.desc(), RawWebhookEvent.id.desc()).limit(limit)
        )
    )
    return [_out(value) for value in values]
