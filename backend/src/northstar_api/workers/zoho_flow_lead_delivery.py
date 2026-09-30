from __future__ import annotations

import asyncio
import signal
from uuid import UUID

import httpx
import structlog
from aiokafka import AIOKafkaConsumer  # type: ignore[import-untyped]
from aiokafka.structs import TopicPartition
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context
from northstar_api.lead_crm.models import LeadProfile
from northstar_api.logging import configure_logging
from northstar_api.models import Lead, ProcessedEvent
from northstar_api.services.education_conversation_policy import is_education_lead
from northstar_api.workers.event_utils import EventEnvelope, parse_envelope, quarantine_event

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)

CONSUMER_NAME = "zoho-flow-lead-delivery-v1"
TOPICS = ("lead.created.v1", "lead.updated.v1")


def build_flow_payload(lead: Lead, profile: LeadProfile | None, event_id: UUID) -> dict[str, object]:
    """Build the small, stable payload consumed by the Zoho Flow trigger."""
    name_parts = (lead.name or "").strip().split(None, 1)
    first_name = (profile.first_name if profile else None) or (name_parts[0] if name_parts else None)
    last_name = (profile.last_name if profile else None) or (name_parts[1] if len(name_parts) > 1 else None)
    if not first_name and not last_name:
        first_name, last_name = "Anonymous", "Visitor"

    fields = lead.fields_json or {}
    return {
        "lead_id": str(lead.id),
        "workspace_id": str(lead.workspace_id),
        "first_name": first_name,
        "last_name": last_name,
        "email": lead.email or None,
        "phone": lead.phone or None,
        "status": lead.status,
        "source": (profile.source_channel if profile else None)
        or fields.get("sourceChannel")
        or (profile.source_provider if profile else None),
        "event_id": str(event_id),
    }


def retry_delay(attempt: int) -> int:
    return min(60, 2 ** min(max(attempt - 1, 0), 6))


def _lead_id(event: EventEnvelope) -> UUID:
    try:
        return UUID(str(event.payload["leadId"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Lead event has no valid leadId") from exc


async def _was_processed(factory: async_sessionmaker, event: EventEnvelope) -> bool:
    async with factory() as session:
        await set_tenant_context(session, event.tenant_id)
        return await session.scalar(
            select(ProcessedEvent.event_id).where(
                ProcessedEvent.event_id == event.event_id,
                ProcessedEvent.consumer == CONSUMER_NAME,
            )
        ) is not None


async def _lead_payload(factory: async_sessionmaker, event: EventEnvelope) -> dict[str, object] | None:
    lead_id = _lead_id(event)
    workspace_id = settings.zoho_flow_lead_workspace_id
    if workspace_id is None:
        return None
    async with factory() as session:
        await set_tenant_context(session, event.tenant_id)
        lead = await session.scalar(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.tenant_id == event.tenant_id,
                Lead.workspace_id == workspace_id,
            )
        )
        if lead is None or await is_education_lead(session, lead_id):
            return None
        profile = await session.scalar(
            select(LeadProfile).where(
                LeadProfile.lead_id == lead_id,
                LeadProfile.tenant_id == event.tenant_id,
            )
        )
        return build_flow_payload(lead, profile, event.event_id)


async def _mark_processed(factory: async_sessionmaker, event: EventEnvelope) -> None:
    async with factory() as session:
        await set_tenant_context(session, event.tenant_id)
        await session.execute(
            pg_insert(ProcessedEvent)
            .values(event_id=event.event_id, consumer=CONSUMER_NAME)
            .on_conflict_do_nothing(index_elements=[ProcessedEvent.event_id, ProcessedEvent.consumer])
        )
        await session.commit()


async def consume_forever() -> None:
    webhook_secret = settings.zoho_flow_lead_webhook_url
    webhook_url = webhook_secret.get_secret_value() if webhook_secret else ""
    if not webhook_url or settings.zoho_flow_lead_workspace_id is None:
        logger.error("zoho_flow_lead_delivery_disabled", reason="webhook_or_workspace_scope_missing")
        return

    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        enable_auto_commit=False,
        auto_offset_reset="latest",
        client_id="northstar-zoho-flow-leads",
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass

    timeout = httpx.Timeout(settings.zoho_flow_webhook_timeout_seconds)
    retry_counts: dict[tuple[str, int, int], int] = {}
    await consumer.start()
    logger.info("zoho_flow_lead_delivery_started", topics=TOPICS)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            while not stop.is_set():
                batches = await consumer.getmany(timeout_ms=1000, max_records=10)
                for messages in batches.values():
                    for message in messages:
                        topic_partition = TopicPartition(message.topic, message.partition)
                        raw = message.value if isinstance(message.value, bytes) else b""
                        try:
                            event = parse_envelope(raw)
                            if event.event_type != message.topic or event.event_type not in TOPICS:
                                raise ValueError("event type does not match a Zoho Flow lead topic")
                            _lead_id(event)
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
                            if not await _was_processed(factory, event):
                                payload = await _lead_payload(factory, event)
                                if payload is not None:
                                    response = await client.post(
                                        webhook_url,
                                        json=payload,
                                        headers={"Idempotency-Key": str(event.event_id)},
                                    )
                                    response.raise_for_status()
                                await _mark_processed(factory, event)
                            await consumer.commit({topic_partition: message.offset + 1})
                            retry_counts.pop((message.topic, message.partition, message.offset), None)
                            logger.info(
                                "zoho_flow_lead_delivered",
                                event_id=str(event.event_id),
                                lead_id=str(_lead_id(event)),
                                event_type=event.event_type,
                            )
                        except Exception as exc:
                            retry_key = (message.topic, message.partition, message.offset)
                            attempt = retry_counts.get(retry_key, 0) + 1
                            retry_counts[retry_key] = attempt
                            logger.warning(
                                "zoho_flow_lead_delivery_retry",
                                event_id=str(event.event_id),
                                lead_id=str(_lead_id(event)),
                                attempt=attempt,
                                error=type(exc).__name__,
                                http_status=(
                                    exc.response.status_code
                                    if isinstance(exc, httpx.HTTPStatusError)
                                    else None
                                ),
                            )
                            consumer.seek(topic_partition, message.offset)
                            try:
                                await asyncio.wait_for(stop.wait(), timeout=retry_delay(attempt))
                            except TimeoutError:
                                pass
                            break
    finally:
        await consumer.stop()
        await engine.dispose()
        logger.info("zoho_flow_lead_delivery_stopped")


def main() -> None:
    if not settings.kafka_enabled:
        raise SystemExit("KAFKA_ENABLED must be true for Zoho Flow lead delivery")
    asyncio.run(consume_forever())


if __name__ == "__main__":
    main()
