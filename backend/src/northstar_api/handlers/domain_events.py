"""One-shot SNS/SQS event dispatcher under construction for the planned tier.

No subscription is created until every legacy consumer has a verified route.
Unsupported events fail closed and must not be acknowledged by an SQS trigger.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import orjson
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import (
    build_engine,
    set_tenant_context,
    sleeping_job_database_settings,
    tenant_context,
)
from northstar_api.models import ProcessedEvent
from northstar_api.services.notifications import project_notification_event
from northstar_api.workers.event_utils import EventEnvelope, parse_envelope

ANALYTICS_TYPES = frozenset({
    "chat.response.completed.v1",
    "conversation.state.changed.v1",
    "feedback.recorded.v1",
})
NOTIFICATION_TYPES = frozenset({
    "lead.created.v1",
    "lead.crm.delivery.failed.v1",
    "education.conversation.resolution.context_missing.v1",
})
OBJECT_CLEANER_TYPE = "knowledge.source.deleted.v1"
CHANNEL_TYPE = "channel.event.received.v1"
CRM_WEBHOOK_TYPE = "crm.webhook.received.v1"
CRM_ROUTER_TYPES = frozenset({"lead.crm.sync.requested.v1", "crm.connection.backfill.requested.v1"})
ZOHO_FLOW_TYPES = frozenset({"lead.created.v1", "lead.updated.v1"})
ROUTED_TYPES = (
    ANALYTICS_TYPES | NOTIFICATION_TYPES | CRM_ROUTER_TYPES | ZOHO_FLOW_TYPES |
    {OBJECT_CLEANER_TYPE, CHANNEL_TYPE, CRM_WEBHOOK_TYPE}
)
NOTIFICATION_CONSUMER = "notifications-v1"
logger = structlog.get_logger(__name__)


def parse_sns_sqs_record(record: dict[str, Any], *, topic_arn: str, queue_arn: str) -> EventEnvelope:
    if record.get("eventSource") != "aws:sqs" or record.get("eventSourceARN") != queue_arn:
        raise ValueError("SQS event source does not match the approved queue")
    body = record.get("body")
    if not isinstance(body, str):
        raise ValueError("SQS record body must be JSON text")
    try:
        wrapper = orjson.loads(body)
    except orjson.JSONDecodeError as exc:
        raise ValueError("SQS record body is not JSON") from exc
    if not isinstance(wrapper, dict) or wrapper.get("Type") != "Notification":
        raise ValueError("SQS record is not an SNS notification")
    if wrapper.get("TopicArn") != topic_arn:
        raise ValueError("SNS topic ARN does not match the approved topic")
    message = wrapper.get("Message")
    if not isinstance(message, str):
        raise ValueError("SNS message must be JSON text")
    event = parse_envelope(message.encode("utf-8"))
    attribute = wrapper.get("MessageAttributes", {}).get("eventType")
    if not isinstance(attribute, dict) or attribute.get("Type") != "String" or attribute.get("Value") != event.event_type:
        raise ValueError("SNS eventType attribute does not match the event envelope")
    return event


async def dispatch_event(factory: async_sessionmaker, event: EventEnvelope) -> None:
    if event.event_type not in ROUTED_TYPES:
        raise ValueError(f"No one-shot route for event type: {event.event_type}")
    if event.event_type in ANALYTICS_TYPES:
        from northstar_api.workers.analytics_consumer import _analytics_deltas, _project_event

        _analytics_deltas(event)
        async with factory() as session:
            await set_tenant_context(session, event.tenant_id)
            await _project_event(session, event)
    if event.event_type in NOTIFICATION_TYPES:
        async with factory() as session:
            await set_tenant_context(session, event.tenant_id)
            inserted = await session.scalar(
                pg_insert(ProcessedEvent)
                .values(event_id=event.event_id, consumer=NOTIFICATION_CONSUMER)
                .on_conflict_do_nothing(index_elements=[ProcessedEvent.event_id, ProcessedEvent.consumer])
                .returning(ProcessedEvent.event_id)
            )
            if inserted is not None:
                await project_notification_event(
                    session,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    tenant_id=event.tenant_id,
                    payload=event.payload,
                )
            await session.commit()
    if event.event_type == OBJECT_CLEANER_TYPE:
        from northstar_api.workers.object_cleaner import cleanup_object_key, process_cleanup_event

        object_key = cleanup_object_key(event)
        await process_cleanup_event(factory, event, object_key)
    if event.event_type == CHANNEL_TYPE:
        from northstar_api.workers.channel_event_consumer import _process_event, _raw_event_id

        _raw_event_id(event)
        async with factory() as session:
            await _process_event(session, event)
    if event.event_type == CRM_WEBHOOK_TYPE:
        from northstar_api.workers.crm_webhook_consumer import _process, _webhook_id

        _webhook_id(event)
        async with factory() as session:
            await _process(session, event)
    if event.event_type in CRM_ROUTER_TYPES:
        await _route_crm_event(factory, event)
    if event.event_type in ZOHO_FLOW_TYPES:
        await _deliver_zoho_flow_event(factory, event)


async def _route_crm_event(factory: async_sessionmaker, event: EventEnvelope) -> None:
    from northstar_api.services.entitlements import EntitlementError, require_feature
    from northstar_api.workers.crm_router_consumer import (
        BACKFILL_TOPIC,
        _batch_size,
        _cursor,
        _optional_uuid,
        _route_event,
        _uuid_value,
    )

    if event.event_type == BACKFILL_TOPIC:
        _uuid_value(event.payload, "workspaceId", label="workspaceId")
        _uuid_value(event.payload, "connectionId", label="connectionId")
        _batch_size(event.payload)
        _cursor(event.payload)
    else:
        _uuid_value(event.payload, "leadId", label="leadId")
        _optional_uuid(event.payload, "originConnectionId", label="originConnectionId")
    async with factory() as session:
        await set_tenant_context(session, event.tenant_id)
        inserted = await session.scalar(
            pg_insert(ProcessedEvent)
            .values(event_id=event.event_id, consumer="crm-router-v1")
            .on_conflict_do_nothing(index_elements=[ProcessedEvent.event_id, ProcessedEvent.consumer])
            .returning(ProcessedEvent.event_id)
        )
        if inserted is not None:
            try:
                await require_feature(session, tenant_id=event.tenant_id, feature="crm")
            except EntitlementError:
                pass
            else:
                await _route_event(session, event)
        await session.commit()


async def _deliver_zoho_flow_event(factory: async_sessionmaker, event: EventEnvelope) -> None:
    from northstar_api.workers.zoho_flow_lead_delivery import (
        _lead_id,
        _lead_payload,
        _mark_processed,
        _was_processed,
    )

    settings = get_settings()
    secret = settings.zoho_flow_lead_webhook_url
    webhook_url = secret.get_secret_value() if secret else ""
    if not webhook_url or settings.zoho_flow_lead_workspace_id is None:
        return  # Matches the disabled legacy consumer: it does not subscribe.
    _lead_id(event)
    if await _was_processed(factory, event):
        return
    payload = await _lead_payload(factory, event)
    if payload is not None:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.zoho_flow_webhook_timeout_seconds),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Idempotency-Key": str(event.event_id)},
            )
            response.raise_for_status()
    await _mark_processed(factory, event)


async def run(event: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    topic_arn = os.environ.get("PLATFORM_DOMAIN_EVENTS_TOPIC_ARN")
    queue_arn = os.environ.get("PLATFORM_DOMAIN_EVENTS_QUEUE_ARN")
    if not topic_arn or not queue_arn:
        raise ValueError("PLATFORM_DOMAIN_EVENTS_TOPIC_ARN and PLATFORM_DOMAIN_EVENTS_QUEUE_ARN are required")
    records = event.get("Records")
    if not isinstance(records, list) or not records:
        raise ValueError("SQS Records must be a non-empty list")
    if len(records) != 1:
        raise ValueError("domain-event FIFO mapping must use batch_size=1")
    record = records[0]
    if not isinstance(record, dict) or not isinstance(record.get("messageId"), str) or not record["messageId"]:
        raise ValueError("SQS record requires a messageId")
    message_id = record["messageId"]
    context_token = tenant_context.set(None)
    try:
        envelope = parse_sns_sqs_record(record, topic_arn=topic_arn, queue_arn=queue_arn)
        if envelope.event_type not in ROUTED_TYPES:
            raise ValueError(f"No one-shot route for event type: {envelope.event_type}")
        settings = get_settings()
        engine = build_engine(sleeping_job_database_settings(settings))
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            await dispatch_event(factory, envelope)
        finally:
            await engine.dispose()
        return {"batchItemFailures": []}
    except Exception as exc:
        # The event-source mapping must enable ReportBatchItemFailures. Invalid
        # messages are retried and eventually reach the configured DLQ.
        logger.warning("domain_event_delivery_failed", message_id=message_id, error=type(exc).__name__)
        return {"batchItemFailures": [{"itemIdentifier": message_id}]}
    finally:
        tenant_context.reset(context_token)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, list[dict[str, str]]]:
    return asyncio.run(run(event))
