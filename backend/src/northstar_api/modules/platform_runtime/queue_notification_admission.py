"""Idempotent notification admission only; outbound send belongs to a later worker."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .queue_alert_persistence import QueueAlertEpisode
from .queue_notification_persistence import QueueAlertNotification


async def admit_alert_notification(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    episode_id: UUID,
    channel: str,
    episode_generation: datetime,
    now: datetime | None = None,
) -> bool:
    """Insert once per episode generation/channel in caller-owned transaction.

    A new alert generation (re-open after resolution) can notify again.
    Never accept a notification belonging to a different tenant.
    """
    if channel not in {"email", "webhook"}:
        raise ValueError("unsupported notification channel")
    if episode_generation.tzinfo is None:
        raise ValueError("episode generation must be timezone-aware")
    clock = now or datetime.now(UTC)
    episode = await session.scalar(
        select(QueueAlertEpisode).where(
            QueueAlertEpisode.id == episode_id,
            QueueAlertEpisode.tenant_id == tenant_id,
            QueueAlertEpisode.state == "open",
        )
    )
    if episode is None or episode.first_seen_at != episode_generation:
        raise ValueError("episode is missing, resolved or generation changed")
    generation = episode_generation.astimezone(UTC).isoformat()
    dedupe = f"{episode_id}:{generation}:{channel}"
    values = dict(
        id=uuid4(), tenant_id=tenant_id, episode_id=episode_id,
        dedupe_key=dedupe, channel=channel, status="pending", attempts=0,
        created_at=clock, next_attempt_at=clock,
    )
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = pg_insert(QueueAlertNotification).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(QueueAlertNotification).values(**values)
    else:
        raise ValueError("notification outbox requires PostgreSQL or test SQLite")
    result = await session.execute(
        statement.on_conflict_do_nothing(
            index_elements=["tenant_id", "dedupe_key"]
        ).returning(QueueAlertNotification.id)
    )
    return result.scalar_one_or_none() is not None
