from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from aiokafka import AIOKafkaConsumer  # type: ignore[import-untyped]
from aiokafka.structs import TopicPartition  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context
from northstar_api.lead_crm.models import (
    CRMConnection,
    CRMExternalReference,
    CRMWebhookEvent,
    LeadActivityEvent,
    LeadProfile,
)
from northstar_api.logging import configure_logging
from northstar_api.models import Lead, ProcessedEvent
from northstar_api.workers.event_utils import EventEnvelope, parse_envelope, quarantine_event

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)
CONSUMER_NAME = "crm-webhook-sync-v1"
TOPICS = ["crm.webhook.received.v1"]


def _webhook_id(event: EventEnvelope) -> UUID:
    try:
        return UUID(str(event.payload["webhookEventId"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("CRM webhook event has no valid webhookEventId") from exc


def _extract(value: Any, path: str) -> Any:
    current = value
    for part in path.removeprefix("$.").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _parse_modified(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000
        try:
            return datetime.fromtimestamp(raw, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        except ValueError:
            return None
    return None


def _apply_field(lead: Lead, profile: LeadProfile, field: str, value: Any) -> bool:
    if field == "status" and isinstance(value, str):
        lead.status = value[:40]
        profile.lifecycle_status = value[:40]
        return True
    if field == "name" and (value is None or isinstance(value, str)):
        lead.name = value
        return True
    if field == "email" and (value is None or isinstance(value, str)):
        lead.email = value
        return True
    if field == "phone" and (value is None or isinstance(value, str)):
        lead.phone = value
        return True
    if field == "company" and (value is None or isinstance(value, str)):
        profile.company = value
        return True
    if field == "jobTitle" and (value is None or isinstance(value, str)):
        profile.job_title = value
        return True
    if field.startswith("custom."):
        custom = dict(profile.custom_fields_json or {})
        custom[field.removeprefix("custom.")] = value
        profile.custom_fields_json = custom
        return True
    return False


async def _process(session: AsyncSession, event: EventEnvelope) -> None:
    inserted = await session.scalar(
        pg_insert(ProcessedEvent)
        .values(event_id=event.event_id, consumer=CONSUMER_NAME)
        .on_conflict_do_nothing(index_elements=[ProcessedEvent.event_id, ProcessedEvent.consumer])
        .returning(ProcessedEvent.event_id)
    )
    if inserted is None:
        await session.commit()
        return
    await set_tenant_context(session, event.tenant_id)
    webhook = await session.scalar(
        select(CRMWebhookEvent).where(
            CRMWebhookEvent.id == _webhook_id(event),
            CRMWebhookEvent.tenant_id == event.tenant_id,
        )
    )
    if not webhook:
        raise ValueError("CRM webhook event no longer exists")
    connection = await session.scalar(
        select(CRMConnection).where(
            CRMConnection.id == webhook.connection_id,
            CRMConnection.tenant_id == event.tenant_id,
        )
    )
    if not connection:
        raise ValueError("CRM webhook connection no longer exists")
    config = connection.configuration_json or {}
    inbound = config.get("inboundWebhook") if isinstance(config.get("inboundWebhook"), dict) else {}
    record_id = _extract(webhook.payload_json, str(inbound.get("recordIdPath") or "$.recordId"))
    if record_id is None:
        webhook.processing_status = "ignored"
        webhook.last_error = "record_id_missing"
        webhook.processed_at = datetime.now(UTC)
        await session.commit()
        return
    reference = await session.scalar(
        select(CRMExternalReference).where(
            CRMExternalReference.tenant_id == event.tenant_id,
            CRMExternalReference.connection_id == connection.id,
            CRMExternalReference.external_id == str(record_id),
        )
    )
    if not reference:
        webhook.processing_status = "ignored"
        webhook.last_error = "external_reference_not_found"
        webhook.processed_at = datetime.now(UTC)
        await session.commit()
        return
    lead = await session.scalar(
        select(Lead).where(Lead.id == reference.lead_id, Lead.tenant_id == event.tenant_id)
    )
    profile = await session.scalar(
        select(LeadProfile).where(
            LeadProfile.lead_id == reference.lead_id,
            LeadProfile.tenant_id == event.tenant_id,
        )
    )
    if not lead or not profile:
        raise ValueError("Referenced lead is unavailable")

    modified_at = _parse_modified(
        _extract(webhook.payload_json, str(inbound.get("modifiedAtPath") or "$.modifiedAt"))
    )
    policy = str(config.get("conflictPolicy") or "CRM_WINS").upper()
    if policy == "PLATFORM_WINS" and profile.updated_at and modified_at and profile.updated_at > modified_at:
        webhook.processing_status = "ignored"
        webhook.last_error = "platform_newer"
        webhook.processed_at = datetime.now(UTC)
        await session.commit()
        return
    if policy == "LATEST_WINS" and profile.updated_at and modified_at and profile.updated_at > modified_at:
        webhook.processing_status = "ignored"
        webhook.last_error = "platform_newer"
        webhook.processed_at = datetime.now(UTC)
        await session.commit()
        return
    mapping = inbound.get("fieldMapping") if isinstance(inbound.get("fieldMapping"), dict) else {}
    changed: dict[str, Any] = {}
    for target, path in mapping.items():
        if not isinstance(target, str) or not isinstance(path, str):
            continue
        value = _extract(webhook.payload_json, path)
        if value is None:
            continue
        if _apply_field(lead, profile, target, value):
            changed[target] = value

    reference.external_modified_at = modified_at
    reference.sync_version += 1
    reference.change_origin = "crm"
    session.add(
        LeadActivityEvent(
            tenant_id=event.tenant_id,
            lead_id=lead.id,
            event_type="lead.crm.inbound.applied.v1",
            correlation_id=webhook.correlation_id,
            details_json={
                "provider": connection.provider,
                "connectionId": str(connection.id),
                "externalRecordId": str(record_id),
                "fields": list(changed),
                "conflictPolicy": policy,
            },
        )
    )
    webhook.processing_status = "processed"
    webhook.processed_at = datetime.now(UTC)
    webhook.last_error = None
    await session.commit()


async def consume_forever() -> None:
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        client_id="northstar-crm-webhook-sync",
    )
    await consumer.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass
    logger.info("crm_webhook_consumer_started")
    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=1)
            for messages in batch.values():
                for message in messages:
                    tp = TopicPartition(message.topic, message.partition)
                    raw = message.value if isinstance(message.value, bytes) else b""
                    try:
                        envelope = parse_envelope(raw)
                        if envelope.event_type != message.topic:
                            raise ValueError("event type does not match Kafka topic")
                        _webhook_id(envelope)
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
                        await consumer.commit({tp: message.offset + 1})
                        continue
                    try:
                        async with factory() as session:
                            await _process(session, envelope)
                        await consumer.commit({tp: message.offset + 1})
                    except Exception as exc:
                        logger.warning(
                            "crm_webhook_retry",
                            event_id=str(envelope.event_id),
                            error=type(exc).__name__,
                        )
                        consumer.seek(tp, message.offset)
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=1.0)
                        except TimeoutError:
                            pass
    finally:
        await consumer.stop()
        await engine.dispose()
        logger.info("crm_webhook_consumer_stopped")


def main() -> None:
    if not settings.kafka_enabled:
        raise SystemExit("KAFKA_ENABLED must be true for CRM webhook sync")
    asyncio.run(consume_forever())


if __name__ == "__main__":
    main()
