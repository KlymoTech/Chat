from __future__ import annotations

from collections import Counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
from northstar_api.lead_crm.channel_operations_health_schemas import (
    ChannelOperationalConnectionHealthOut,
    ChannelOperationalHealthOut,
)
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.security import Principal

router = APIRouter(prefix="/channels/operations", tags=["channels"])
DB = Annotated[AsyncSession, Depends(get_session)]
ChannelsViewPrincipal = Annotated[Principal, Depends(require_permissions("integrations.view"))]

_PENDING_STATUSES = frozenset({"queued", "processing"})
_RETRYING_STATUSES = frozenset({"failed"})
_FAILED_STATUSES = frozenset({"rejected", "reconnect_required", "dispatch_failed"})
_ATTENTION_CONNECTION_STATUSES = frozenset(
    {
        "degraded",
        "unhealthy",
        "auth_required",
        "rate_limited",
        "configuration_error",
        "reconnect_required",
        "disabled",
    }
)


def _connection_needs_attention(row: ChannelOperationalConnectionHealthOut) -> bool:
    return row.status in _ATTENTION_CONNECTION_STATUSES or row.failed_deliveries > 0


@router.get("/health", response_model=ChannelOperationalHealthOut)
async def channel_operational_health(
    principal: ChannelsViewPrincipal,
    session: DB,
) -> ChannelOperationalHealthOut:
    """Summarize current provider-neutral channel operations for the active Workspace."""

    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")

    connections = list(
        await session.scalars(
            select(ChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.workspace_id == principal.workspace_id,
            )
            .order_by(ChannelConnection.created_at, ChannelConnection.id)
        )
    )
    connection_ids = [connection.id for connection in connections]

    delivery_counts: dict[UUID, Counter[str]] = {}
    if connection_ids:
        rows = list(
            await session.execute(
                select(ChannelOutboundDelivery.connection_id, ChannelOutboundDelivery.status).where(
                    ChannelOutboundDelivery.tenant_id == principal.tenant_id,
                    ChannelOutboundDelivery.workspace_id == principal.workspace_id,
                    ChannelOutboundDelivery.connection_id.in_(connection_ids),
                )
            )
        )
        for connection_id, status in rows:
            if connection_id is not None:
                delivery_counts.setdefault(connection_id, Counter())[status] += 1

    connection_rows: list[ChannelOperationalConnectionHealthOut] = []
    for connection in connections:
        counts = delivery_counts.get(connection.id, Counter())
        pending = sum(counts[status] for status in _PENDING_STATUSES)
        retrying = sum(counts[status] for status in _RETRYING_STATUSES)
        failed = sum(counts[status] for status in _FAILED_STATUSES)
        connection_rows.append(
            ChannelOperationalConnectionHealthOut(
                connection_id=connection.id,
                name=connection.name,
                provider=connection.provider,
                status=connection.status,
                last_health_at=connection.last_health_at,
                last_event_at=connection.last_event_at,
                last_failure_at=connection.last_failure_at,
                last_error=connection.last_error,
                pending_deliveries=pending,
                retrying_deliveries=retrying,
                failed_deliveries=failed,
            )
        )

    attention_connections = sum(
        1 for row in connection_rows if _connection_needs_attention(row)
    )
    healthy_connections = sum(
        1
        for row in connection_rows
        if row.status == "healthy" and not _connection_needs_attention(row)
    )
    pending_total = sum(row.pending_deliveries for row in connection_rows)
    retrying_total = sum(row.retrying_deliveries for row in connection_rows)
    failed_total = sum(row.failed_deliveries for row in connection_rows)
    has_nonhealthy_nonattention_connection = any(
        row.status != "healthy" and not _connection_needs_attention(row)
        for row in connection_rows
    )

    if not connection_rows:
        overall_status = "empty"
    elif attention_connections:
        overall_status = "attention"
    elif retrying_total or pending_total or has_nonhealthy_nonattention_connection:
        overall_status = "active"
    else:
        overall_status = "healthy"

    return ChannelOperationalHealthOut(
        overall_status=overall_status,
        connection_count=len(connection_rows),
        healthy_connections=healthy_connections,
        attention_connections=attention_connections,
        pending_deliveries=pending_total,
        retrying_deliveries=retrying_total,
        failed_deliveries=failed_total,
        connections=connection_rows,
    )
