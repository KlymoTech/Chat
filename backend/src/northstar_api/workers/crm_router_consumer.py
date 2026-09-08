from __future__ import annotations

import asyncio
import signal
from uuid import UUID

import structlog
from aiokafka import AIOKafkaConsumer  # type: ignore[import-untyped]
from aiokafka.structs import TopicPartition  # type: ignore[import-untyped]
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.lead_crm.services import crm_route_service
from northstar_api.logging import configure_logging
from northstar_api.models import ProcessedEvent
from northstar_api.workers.event_utils import parse_envelope, quarantine_event

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)
CONSUMER_NAME = "crm-router-v1"
TOPICS = ["lead.crm.sync.requested.v1"]


def _lead_id(payload: dict[str, object]) -> UUID:
    try:
        return UUID(str(payload["leadId"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("CRM sync event has no valid leadId") from exc


async def consume_forever() -> None:
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        client_id="northstar-crm-router",
    )
    await consumer.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass
    logger.info("crm_router_consumer_started")
    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=10)
            for messages in batch.values():
                for message in messages:
                    topic_partition = TopicPartition(message.topic, message.partition)
                    raw = message.value if isinstance(message.value, bytes) else b""
                    try:
                        event = parse_envelope(raw)
                        if event.event_type != message.topic:
                            raise ValueError("event type does not match Kafka topic")
                        lead_id = _lead_id(event.payload)
                    except ValueError as exc:
                        async with factory() as session:
                            await quarantine_event(
                                session,
                                consumer=CONSUMER_NAME,
                                topic=message.topic,
                                partition=message.partition,
                                offset=message.offset,
                                raw=raw,
                                error=exc,
                            )
                        await consumer.commit({topic_partition: message.offset + 1})
                        continue
                    try:
                        async with factory() as session:
                            inserted = await session.scalar(
                                pg_insert(ProcessedEvent)
                                .values(event_id=event.event_id, consumer=CONSUMER_NAME)
                                .on_conflict_do_nothing(
                                    index_elements=[ProcessedEvent.event_id, ProcessedEvent.consumer]
                                )
                                .returning(ProcessedEvent.event_id)
                            )
                            if inserted is not None:
                                deliveries = await crm_route_service.create_deliveries(
                                    session,
                                    tenant_id=event.tenant_id,
                                    lead_id=lead_id,
                                    correlation_id=str(event.event_id),
                                )
                                await session.commit()
                                logger.info(
                                    "crm_routes_evaluated",
                                    event_id=str(event.event_id),
                                    lead_id=str(lead_id),
                                    delivery_count=len(deliveries),
                                )
                            else:
                                await session.commit()
                        await consumer.commit({topic_partition: message.offset + 1})
                    except Exception as exc:
                        logger.warning(
                            "crm_router_retry",
                            event_id=str(event.event_id),
                            error=type(exc).__name__,
                        )
                        consumer.seek(topic_partition, message.offset)
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=1.0)
                        except TimeoutError:
                            pass
                        break  # Do not advance past a failed partition offset.
    finally:
        await consumer.stop()
        await engine.dispose()
        logger.info("crm_router_consumer_stopped")


def main() -> None:
    if not settings.kafka_enabled:
        raise SystemExit("KAFKA_ENABLED must be true for the CRM router consumer")
    asyncio.run(consume_forever())


if __name__ == "__main__":
    main()
