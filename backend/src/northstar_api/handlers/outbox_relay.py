"""Bounded, queue-triggered outbox relay for the planned scale-to-zero tier.

The legacy continuously polling worker remains available for existing deployments.
An SQS trigger invokes this handler; a single invocation never sleeps or polls.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import orjson
from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.models import OutboxEvent
from northstar_api.services.outbox import send_outbox_nudge

BATCH_SIZE = 100


def event_envelope(event: OutboxEvent) -> dict[str, Any]:
    return {
        "eventId": str(event.id),
        "eventType": event.event_type,
        "schemaVersion": 1,
        "tenantId": str(event.tenant_id),
        "aggregateType": event.aggregate_type,
        "aggregateId": event.aggregate_id,
        "occurredAt": event.occurred_at.isoformat(),
        "payload": event.payload,
    }


async def publish_batch(session: AsyncSession, producer: AIOKafkaProducer) -> int:
    """Publish one locked batch; raise on failure so the queue can retry.

    A broker acknowledgement can precede a failed database commit. Consumers must
    deduplicate by eventId; exactly-once delivery is not promised.
    """
    events = (
        await session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.occurred_at)
            .with_for_update(skip_locked=True)
            .limit(BATCH_SIZE)
        )
    ).all()
    published = 0
    for event in events:
        try:
            await producer.send_and_wait(
                event.event_type, event_envelope(event), key=event.aggregate_id
            )
        except Exception as exc:
            event.attempts += 1
            event.last_error = type(exc).__name__[:500]
            await session.commit()
            raise
        event.published_at = datetime.now(UTC)
        event.last_error = None
        published += 1
    await session.commit()
    return published


async def run_once() -> int:
    settings = get_settings()
    if not settings.kafka_enabled:
        raise ValueError("KAFKA_ENABLED must be true for the outbox relay")
    engine = build_engine(settings)
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks="all",
        enable_idempotence=True,
        compression_type="gzip",
        value_serializer=orjson.dumps,
        key_serializer=lambda value: value.encode(),
        client_id="northstar-outbox-once",
    )
    started = False
    try:
        await producer.start()
        started = True
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            return await publish_batch(session, producer)
    finally:
        if started:
            await producer.stop()
        await engine.dispose()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    published = asyncio.run(run_once())
    if published == BATCH_SIZE and not send_outbox_nudge():
        raise RuntimeError("outbox relay could not enqueue continuation")
    return {"published": published}
