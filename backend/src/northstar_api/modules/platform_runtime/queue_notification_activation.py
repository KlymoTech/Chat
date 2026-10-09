"""Governed route activation: no sends, no provider SDK and no implicit fallback.

The authenticated application must supply an independently qualified, trusted
preflight. Database activation and audit share the caller-owned transaction.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .queue_notification_config import ApprovedNotificationRoute
from .queue_notification_config_persistence import ApprovedNotificationRouteRecord
from .queue_notification_governance import AuditWriter, RouteConflict

RoutePreflight = Callable[[ApprovedNotificationRoute], Awaitable[bool]]


async def activate_notification_route(
    session: AsyncSession, *, route: ApprovedNotificationRoute,
    expected_revision: int, actor_id: UUID, authorized: bool,
    preflight: RoutePreflight, audit: AuditWriter,
) -> int:
    """Activate an approved revision after trusted preflight and fenced update.

    Approval and activation are separate governance operations. No emails,
    webhooks or notifications are produced by this function.
    """
    if not authorized:
        raise PermissionError("activation requires explicit manage authorization")
    if preflight is None or audit is None:
        raise ValueError("trusted preflight and transactional audit are required")
    if expected_revision < 1 or route.revision != expected_revision:
        raise RouteConflict("route revision changed")
    if not route.approved or route.enabled:
        raise RouteConflict("route is not approved or already enabled")
    try:
        preflight_ok = await preflight(route)
    except Exception:
        preflight_ok = False
    if preflight_ok is not True:
        raise RouteConflict("notification route preflight failed")

    result = await session.execute(
        update(ApprovedNotificationRouteRecord)
        .where(
            ApprovedNotificationRouteRecord.tenant_id == route.tenant_id,
            ApprovedNotificationRouteRecord.channel == route.channel,
            ApprovedNotificationRouteRecord.revision == expected_revision,
            ApprovedNotificationRouteRecord.destination_reference == route.destination_reference,
            ApprovedNotificationRouteRecord.approved.is_(True),
            ApprovedNotificationRouteRecord.enabled.is_(False),
            ApprovedNotificationRouteRecord.approved_by.is_not(None),
        )
        .values(
            enabled=True,
            revision=expected_revision + 1,
            updated_at=datetime.now(UTC),
        )
    )
    if result.rowcount != 1:
        raise RouteConflict("notification route changed during preflight")
    revision = expected_revision + 1
    await audit(session, {
        "action": "platform.notification_route.activated",
        "tenant_id": str(route.tenant_id), "channel": route.channel,
        "revision": str(revision), "actor_id": str(actor_id),
    })
    return revision
