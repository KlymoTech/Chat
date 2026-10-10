"""Governed notification-route drafting and approval.

Application must authenticate/authorize actors before calling these functions.
All changes and audit writes share the caller-owned transaction. No route is
enabled here; enabling delivery requires a separate qualified change.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .queue_notification_config import ApprovedNotificationRoute
from .queue_notification_config_persistence import ApprovedNotificationRouteRecord

AuditWriter = Callable[[AsyncSession, dict[str, str]], Awaitable[None]]


class RouteConflict(ValueError):
    pass


async def draft_notification_route(
    session: AsyncSession, *, tenant_id: UUID, channel: str,
    destination_reference: str, actor_id: UUID, authorized: bool,
    expected_revision: int, audit: AuditWriter,
) -> int:
    if not authorized:
        raise PermissionError("route configuration requires manage authorization")
    if audit is None:
        raise ValueError("transactional audit required")
    if expected_revision < 0:
        raise ValueError("invalid expected revision")
    ApprovedNotificationRoute(
        tenant_id, channel, destination_reference, 1, False, False
    )
    clock = datetime.now(UTC)
    if expected_revision == 0:
        # Unique tenant/channel constraint guards simultaneous first drafts.
        session.add(ApprovedNotificationRouteRecord(
            id=uuid4(), tenant_id=tenant_id, channel=channel,
            destination_reference=destination_reference, revision=1,
            enabled=False, approved=False, proposed_by=actor_id,
            approved_by=None, updated_at=clock,
        ))
        # Flush now so audit cannot report success if insertion fails.
        await session.flush()
        revision = 1
    else:
        response = await session.execute(
            update(ApprovedNotificationRouteRecord)
            .where(
                ApprovedNotificationRouteRecord.tenant_id == tenant_id,
                ApprovedNotificationRouteRecord.channel == channel,
                ApprovedNotificationRouteRecord.revision == expected_revision,
            )
            .values(
                destination_reference=destination_reference,
                revision=expected_revision + 1,
                enabled=False, approved=False, proposed_by=actor_id,
                approved_by=None, updated_at=clock,
            )
        )
        if response.rowcount != 1:
            raise RouteConflict("route revision changed or tenant/channel not found")
        revision = expected_revision + 1
    await audit(session, {
        "action": "platform.notification_route.drafted",
        "tenant_id": str(tenant_id), "channel": channel,
        "revision": str(revision), "actor_id": str(actor_id),
    })
    return revision


async def approve_notification_route(
    session: AsyncSession, *, tenant_id: UUID, channel: str,
    revision: int, actor_id: UUID, authorized: bool, audit: AuditWriter,
) -> None:
    if not authorized:
        raise PermissionError("route approval requires approval authorization")
    if audit is None:
        raise ValueError("transactional audit required")
    if revision < 1 or channel not in ("email", "webhook"):
        raise ValueError("invalid route revision or channel")
    response = await session.execute(
        update(ApprovedNotificationRouteRecord)
        .where(
            ApprovedNotificationRouteRecord.tenant_id == tenant_id,
            ApprovedNotificationRouteRecord.channel == channel,
            ApprovedNotificationRouteRecord.revision == revision,
            ApprovedNotificationRouteRecord.approved.is_(False),
            ApprovedNotificationRouteRecord.proposed_by.is_not(None),
            ApprovedNotificationRouteRecord.proposed_by != actor_id,
        )
        .values(approved=True, approved_by=actor_id, enabled=False,
                updated_at=datetime.now(UTC))
    )
    if response.rowcount != 1:
        raise RouteConflict("route unavailable, already approved, or same actor")
    await audit(session, {
        "action": "platform.notification_route.approved",
        "tenant_id": str(tenant_id), "channel": channel,
        "revision": str(revision), "actor_id": str(actor_id),
    })


async def deactivate_notification_route(
    session: AsyncSession, *, tenant_id: UUID, channel: str,
    expected_revision: int, actor_id: UUID, authorized: bool,
    audit: AuditWriter,
) -> int:
    """Disable a route via compare-and-swap, retaining its approval history.

    Deactivation advances the revision to prevent stale administrative writes.
    The caller commits mutation and audit in a single transaction.
    """
    if not authorized:
        raise PermissionError("route deactivation requires manage authorization")
    if audit is None:
        raise ValueError("transactional audit required")
    if channel not in ("email", "webhook") or expected_revision < 1:
        raise ValueError("invalid channel or expected revision")
    statement = (
        update(ApprovedNotificationRouteRecord)
        .where(
            ApprovedNotificationRouteRecord.tenant_id == tenant_id,
            ApprovedNotificationRouteRecord.channel == channel,
            ApprovedNotificationRouteRecord.revision == expected_revision,
        )
        .values(
            enabled=False,
            revision=expected_revision + 1,
            updated_at=datetime.now(UTC),
        )
    )
    result = await session.execute(statement)
    if result.rowcount != 1:
        raise RouteConflict("route revision changed or tenant/channel not found")
    revision = expected_revision + 1
    await audit(session, {
        "action": "platform.notification_route.deactivated",
        "tenant_id": str(tenant_id),
        "channel": channel,
        "revision": str(revision),
        "actor_id": str(actor_id),
    })
    return revision
