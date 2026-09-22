"""Machine-to-machine callback surface for the platform deployment executor."""

from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select

from northstar_api.config import get_settings
from northstar_api.dependencies import DBSession
from northstar_api.models import OutboxEvent
from northstar_api.modules.platform_runtime import DeploymentExecutionReport
from northstar_api.modules.super_admin.api.runtime import (
    RuntimeExecutionOut,
    persist_runtime_execution_report,
)

PLATFORM_CHANGE_EVENT_TYPE = "platform.runtime.change.approved.v1"

router = APIRouter(prefix="/platform-executor", tags=["platform executor"])


ExecutorAuthorization = Annotated[
    str | None,
    Header(alias="Authorization", include_in_schema=False),
]


def _require_executor_token(authorization: str | None) -> None:
    settings = get_settings()
    configured = settings.platform_change_report_token
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="platform executor reporting is not configured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="platform executor credential required",
        )
    supplied = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, configured.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="platform executor credential is invalid",
        )


@router.post(
    "/changes/{change_id}/executions",
    response_model=RuntimeExecutionOut,
    status_code=status.HTTP_201_CREATED,
)
async def report_platform_executor_execution(
    change_id: UUID,
    payload: DeploymentExecutionReport,
    authorization: ExecutorAuthorization,
    session: DBSession,
) -> RuntimeExecutionOut:
    """Record executor evidence without requiring a human administrator token."""
    _require_executor_token(authorization)
    source_event = await session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_type == "platform_change",
            OutboxEvent.aggregate_id == str(change_id),
            OutboxEvent.event_type == PLATFORM_CHANGE_EVENT_TYPE,
        )
    )
    if source_event is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="platform change has no approved deployment dispatch event",
        )
    return await persist_runtime_execution_report(
        change_id,
        payload,
        session,
        audit_tenant_id=source_event.tenant_id,
        actor_user_id=None,
        actor_type="platform-executor",
    )


__all__ = ["router"]
