from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.logging import request_id_ctx


def record_integration_audit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    session.add(
        IntegrationAuditEvent(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action[:160],
            entity_type=entity_type[:100],
            entity_id=entity_id[:160],
            before_json=before or {},
            after_json=after or {},
            request_id=request_id_ctx.get(),
            ip_address=request.client.host[:80] if request and request.client else None,
            user_agent=request.headers.get("user-agent", "")[:500] if request else None,
        )
    )
