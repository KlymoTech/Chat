from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from aiokafka import AIOKafkaConsumer  # type: ignore[import-untyped]
from aiokafka.structs import TopicPartition  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context, tenant_context
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.logging import configure_logging
from northstar_api.models import Conversation, Message, MessageRole, ProcessedEvent
from northstar_api.workers.event_utils import EventEnvelope, parse_envelope, quarantine_event
from northstar_api.workers.instagram_tasks import send_instagram_message

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)
CONSUMER_NAME = "instagram-outbound-v1"
TOPICS = ["chat.message.created.v1"]


class InstagramProjectionError(RuntimeError):
    pass


def instagram_recipient_id(conversation: Conversation) -> str | None:
    visitor_id = (conversation.visitor_id or "").strip()
    if not visitor_id.startswith("instagram:"):
        return None
    value = visitor_id.removeprefix("instagram:").strip()
    return value if value and len(value) <= 180 else None


def _uuid_payload(event: EventEnvelope, key: str) -> UUID:
    try:
        return UUID(str(event.payload[key]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Instagram outbound event has no valid {key}") from exc


async def _mark_processed(session: AsyncSession, event: EventEnvelope) -> None:
    if await session.get(ProcessedEvent, (event.event_id, CONSUMER_NAME)) is None:
        session.add(ProcessedEvent(event_id=event.event_id, consumer=CONSUMER_NAME))


async def _matching_connection(
    session: AsyncSession,
    *,
    event: EventEnvelope,
    workspace_id: UUID,
    agent_id: UUID,
) -> ChannelConnection:
    rows = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.tenant_id == event.tenant_id,
                ChannelConnection.provider == ChannelProvider.INSTAGRAM.value,
                ChannelConnection.status != "disabled",
                WorkspaceChannelConnection.tenant_id == event.tenant_id,
                WorkspaceChannelConnection.workspace_id == workspace_id,
            )
            .with_for_update()
        )
    ).all()
    matches = [
        connection
        for connection, scope in rows
        if (scope.agent_id is None or scope.agent_id == agent_id)
        and str((connection.configuration_json or {}).get("agentId") or "") == str(agent_id)
    ]
    if not matches:
        raise InstagramProjectionError("Instagram is not connected for this agent")
    if len(matches) > 1:
        raise InstagramProjectionError(
            "Multiple Instagram connections match this agent; disable the duplicate connection before replying"
        )
    return matches[0]


async def project_instagram_delivery(
    session: AsyncSession,
    event: EventEnvelope,
) -> ChannelOutboundDelivery | None:
    if str(event.payload.get("role") or "") != "agent":
        return None
    message_id = _uuid_payload(event, "messageId")
    conversation_id = _uuid_payload(event, "conversationId")
    message = await session.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.tenant_id == event.tenant_id,
            Message.role == MessageRole.AGENT,
        )
    )
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == event.tenant_id,
        )
    )
    if not message or not conversation or message.conversation_id != conversation.id:
        raise InstagramProjectionError("Instagram outbound message or conversation is unavailable")
    recipient_id = instagram_recipient_id(conversation)
    if recipient_id is None:
        return None
    if message.workspace_id != conversation.workspace_id:
        raise InstagramProjectionError("Instagram outbound message workspace does not match conversation")

    existing = await session.scalar(
        select(ChannelOutboundDelivery).where(
            ChannelOutboundDelivery.provider == ChannelProvider.INSTAGRAM.value,
            ChannelOutboundDelivery.message_id == message.id,
        )
    )
    if existing is not None:
        if existing.tenant_id != event.tenant_id or existing.workspace_id != conversation.workspace_id:
            raise InstagramProjectionError("Instagram delivery scope is inconsistent")
        return existing

    connection = await _matching_connection(
        session,
        event=event,
        workspace_id=conversation.workspace_id,
        agent_id=conversation.agent_id,
    )
    delivery = ChannelOutboundDelivery(
        tenant_id=event.tenant_id,
        workspace_id=conversation.workspace_id,
        connection_id=connection.id,
        message_id=message.id,
        provider=ChannelProvider.INSTAGRAM.value,
        recipient_external_id=recipient_id,
        status="queued",
    )
    session.add(delivery)
    message.finish_reason = "queued"
    await session.flush()
    return delivery


async def _process_event(session: AsyncSession, event: EventEnvelope) -> ChannelOutboundDelivery | None:
    if await session.get(ProcessedEvent, (event.event_id, CONSUMER_NAME)) is not None:
        return None
    try:
        delivery = await project_instagram_delivery(session, event)
    except InstagramProjectionError as exc:
        message_id_value = event.payload.get("messageId")
        try:
            message_id = UUID(str(message_id_value))
        except (TypeError, ValueError):
            message_id = None
        if message_id is not None:
            message = await session.get(Message, message_id)
            if message and message.tenant_id == event.tenant_id:
                message.finish_reason = "failed"
        await _mark_processed(session, event)
        await session.commit()
        logger.warning(
            "instagram_outbound_projection_rejected",
            event_id=str(event.event_id),
            error=str(exc),
        )
        return None

    if delivery is None:
        await _mark_processed(session, event)
        await session.commit()
        return None

    # Persist the delivery before publishing to RabbitMQ. If dispatch fails, the
    # Kafka offset stays uncommitted and the event is retried. If a crash occurs
    # after publish but before ProcessedEvent is stored, the worker's row lock and
    # terminal-state check make a duplicate Celery task harmless.
    await session.commit()
    try:
        await asyncio.to_thread(
            send_instagram_message.apply_async,
            args=[str(delivery.id)],
            queue="instagram.outbound",
            routing_key="instagram.outbound",
        )
    except Exception:
        delivery = await session.get(ChannelOutboundDelivery, delivery.id)
        if delivery:
            delivery.dispatch_attempts += 1
            delivery.status = "failed"
            delivery.next_dispatch_at = datetime.now(UTC)
            delivery.last_error = "queue dispatch unavailable"
            await session.commit()
        raise

    delivery = await session.get(ChannelOutboundDelivery, delivery.id)
    if delivery:
        delivery.dispatch_attempts += 1
        delivery.dispatched_at = datetime.now(UTC)
        delivery.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
        delivery.last_error = None
    await _mark_processed(session, event)
    await session.commit()
    return delivery


async def consume_forever() -> None:
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=CONSUMER_NAME,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        client_id="northstar-instagram-outbound",
    )
    await consumer.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass
    logger.info("instagram_outbound_consumer_started")
    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=50)
            for messages in batch.values():
                for message in messages:
                    topic_partition = TopicPartition(message.topic, message.partition)
                    raw = message.value if isinstance(message.value, bytes) else b""
                    try:
                        event = parse_envelope(raw)
                        if event.event_type != message.topic:
                            raise ValueError("event type does not match Kafka topic")
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

                    context_token = tenant_context.set(None)
                    try:
                        async with factory() as session:
                            await set_tenant_context(session, event.tenant_id)
                            await _process_event(session, event)
                        await consumer.commit({topic_partition: message.offset + 1})
                    except Exception as exc:
                        logger.warning(
                            "instagram_outbound_event_retry",
                            event_id=str(event.event_id),
                            error=type(exc).__name__,
                        )
                        consumer.seek(topic_partition, message.offset)
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=1.0)
                        except TimeoutError:
                            pass
                        break
                    finally:
                        tenant_context.reset(context_token)
    finally:
        await consumer.stop()
        await engine.dispose()
        logger.info("instagram_outbound_consumer_stopped")


def main() -> None:
    if not settings.kafka_enabled:
        raise SystemExit("KAFKA_ENABLED must be true for the Instagram outbound consumer")
    asyncio.run(consume_forever())


if __name__ == "__main__":
    main()
