"""Transactional queue alert episode reconciliation, independent of delivery."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .queue_alert_persistence import QueueAlertEpisode
from .queue_alerts import QueueAlert


async def reconcile_queue_alerts(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    alerts: tuple[QueueAlert, ...],
    observed_at: datetime | None = None,
    resolve_missing: bool = False,
) -> dict[str, int]:
    """Reconcile in the caller's transaction; never commit or send notifications.

    PostgreSQL reconciliations acquire a transaction-scoped advisory lock so
    competing workers serialize even when the first episode does not exist.
    The caller must own a transaction and commit after this method returns.
    Shared broker observations are
    tracked per observing tenant, not mistakenly marked as tenant metrics.
    """
    clock = observed_at or datetime.now(UTC)
    if clock.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    by_code = {(alert.scope, alert.code): alert for alert in alerts}
    if len(by_code) != len(alerts):
        raise ValueError("duplicate alert identities in observation")
    scope_key = f"tenant:{tenant_id}"
    # SELECT FOR UPDATE cannot lock a missing row. Serialize creation and
    # resolution for this tenant before reading the current episode set.
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": "northstar:queue-alert:" + scope_key},
        )
    existing = (await session.scalars(
        select(QueueAlertEpisode)
        .where(QueueAlertEpisode.tenant_id == tenant_id, QueueAlertEpisode.scope_key == scope_key)
        .with_for_update()
    )).all()
    known = {(row.code): row for row in existing}
    opened = resolved = updated = 0
    for (_, code), alert in by_code.items():
        row = known.get(code)
        if row is None:
            session.add(QueueAlertEpisode(
                id=uuid4(), tenant_id=tenant_id, scope_key=scope_key, code=code,
                severity=alert.severity, state="open", first_seen_at=clock,
                last_seen_at=clock, resolved_at=None, occurrences=1,
            ))
            opened += 1
        else:
            if row.state == "resolved":
                row.state = "open"
                row.first_seen_at = clock
                row.resolved_at = None
                opened += 1
            else:
                updated += 1
            row.last_seen_at = clock
            row.severity = alert.severity
            row.occurrences += 1
    active_codes = {code for _, code in by_code}
    for row in existing:
        if resolve_missing and row.code not in active_codes and row.state == "open":
            row.state = "resolved"
            row.resolved_at = clock
            row.last_seen_at = clock
            resolved += 1
    return {"opened": opened, "updated": updated, "resolved": resolved}
