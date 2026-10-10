"""Bounded, queue-triggered outbox relay for the planned scale-to-zero tier.

The legacy continuously polling worker remains available for existing deployments.
An SQS trigger invokes this handler; a single invocation never sleeps or polls.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any, Protocol

import boto3
import orjson
from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]
from botocore.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, sleeping_job_database_settings
from northstar_api.models import OutboxEvent
from northstar_api.services.outbox import send_outbox_nudge

BATCH_SIZE = 100


class EventProducer(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_and_wait(self, topic: str, envelope: dict[str, Any], *, key: str) -> Any: ...


class SnsFifoProducer:
    """Opt-in Stage 0 publisher; SNS acknowledgements are not consumer ACKs."""

    def __init__(self, topic_arn: str) -> None:
        if not topic_arn.startswith(("arn:aws:sns:", "arn:aws-us-gov:sns:")) or not topic_arn.endswith(".fifo"):
            raise ValueError("PLATFORM_DOMAIN_EVENTS_TOPIC_ARN must be an SNS FIFO topic ARN")
        self.topic_arn = topic_arn
        self.client = boto3.client(
            "sns", config=Config(connect_timeout=2, read_timeout=10, retries={"max_attempts": 2})
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_and_wait(self, topic: str, envelope: dict[str, Any], *, key: str) -> Any:
        group = f"{envelope['tenantId']}:{key}"
        if len(group) > 128:
            raise ValueError("SNS FIFO message group exceeds 128 characters")
        return await asyncio.to_thread(
            self.client.publish,
            TopicArn=self.topic_arn,
            Message=orjson.dumps(envelope).decode("utf-8"),
            MessageGroupId=group,
            MessageDeduplicationId=envelope["eventId"],
            MessageAttributes={
                "eventType": {"DataType": "String", "StringValue": topic},
            },
        )


def make_producer(settings: Any) -> EventProducer:
    backend = os.environ.get("PLATFORM_EVENTS_BACKEND", "kafka").lower()
    if backend == "sns":
        return SnsFifoProducer(os.environ.get("PLATFORM_DOMAIN_EVENTS_TOPIC_ARN", ""))
    if backend != "kafka":
        raise ValueError("PLATFORM_EVENTS_BACKEND must be kafka or sns")
    if not settings.kafka_enabled:
        raise ValueError("KAFKA_ENABLED must be true for the Kafka outbox relay")
    return AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks="all",
        enable_idempotence=True,
        compression_type="gzip",
        value_serializer=orjson.dumps,
        key_serializer=lambda value: value.encode(),
        client_id="northstar-outbox-once",
    )


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


async def publish_batch(session: AsyncSession, producer: EventProducer) -> int:
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
    producer = make_producer(settings)
    engine = build_engine(sleeping_job_database_settings(settings))
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
