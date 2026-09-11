from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Load, selectinload

from northstar_api.config import get_settings
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import (
    Channel,
    Conversation,
    ConversationState,
    Message,
    MessageRole,
    WhatsAppConnection,
    WhatsAppInboundMessage,
    WhatsAppOutboundDelivery,
)
from northstar_api.schemas import (
    CitationOut,
    ConversationOut,
    ConversationPatch,
    ConversationReplyCreate,
    MessageOut,
    PageResult,
)
from northstar_api.security import Principal
from northstar_api.services.conversation_resolution import conversation_resolution_service
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.whatsapp import token_expiry_is_current
from northstar_api.workers.tasks import send_whatsapp_human_reply
from northstar_api.workers.telegram_tasks import send_telegram_message

router = APIRouter(prefix="/conversations", tags=["conversations"])
DB = Annotated[AsyncSession, Depends(get_session)]
ConversationsViewPrincipal = Annotated[Principal, Depends(require_permissions("conversations.view"))]
ConversationsResolvePrincipal = Annotated[Principal, Depends(require_permissions("conversations.resolve"))]
ConversationsReplyPrincipal = Annotated[Principal, Depends(require_permissions("conversations.reply"))]


def conversation_response(conversation: Conversation) -> ConversationOut:
    messages = [
        MessageOut(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            citations=[CitationOut(title=item.title, url=item.url) for item in message.citations],
        )
        for message in conversation.messages
    ]
    preview = messages[-1].content[:240] if messages else "No messages yet"
    return ConversationOut(
        id=conversation.id,
        workspace_id=conversation.workspace_id,
        agent_id=conversation.agent_id,
        visitor_name=conversation.visitor_name,
        visitor_email=conversation.visitor_email,
        channel=conversation.channel,
        state=conversation.state,
        sentiment=conversation.sentiment,
        preview=preview,
        unread=conversation.unread_count,
        started_at=conversation.started_at,
        updated_at=conversation.updated_at,
        messages=messages,
    )


def conversation_options() -> Load:
    # SQLAlchemy's public type hint is the abstract loader base, while this
    # factory returns a concrete Load instance at runtime.
    return cast(Load, selectinload(Conversation.messages).selectinload(Message.citations))


def conversation_scope(principal: Principal, conversation_id: UUID) -> tuple[object, ...]:
    return (
        Conversation.id == conversation_id,
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
        *((Conversation.agent_id.in_(principal.agent_ids),) if principal.agent_ids is not None else ()),
    )


async def locked_conversation(
    session: AsyncSession,
    principal: Principal,
    conversation_id: UUID,
) -> Conversation | None:
    return await session.scalar(
        select(Conversation)
        .options(conversation_options())
        .where(*conversation_scope(principal, conversation_id))
        .with_for_update()
    )


def _telegram_chat_id(conversation: Conversation) -> str | None:
    visitor_id = conversation.visitor_id or ""
    if not visitor_id.startswith("telegram:"):
        return None
    chat_id = visitor_id.removeprefix("telegram:").strip()
    if not chat_id or not chat_id.lstrip("-").isdigit():
        return None
    return chat_id


async def _telegram_connection_for_conversation(
    session: AsyncSession,
    principal: Principal,
    conversation: Conversation,
) -> tuple[ChannelConnection, str] | None:
    chat_id = _telegram_chat_id(conversation)
    if chat_id is None:
        return None
    rows = (
        await session.execute(
            select(ChannelConnection, WorkspaceChannelConnection)
            .join(
                WorkspaceChannelConnection,
                WorkspaceChannelConnection.connection_id == ChannelConnection.id,
            )
            .where(
                ChannelConnection.tenant_id == principal.tenant_id,
                ChannelConnection.provider == ChannelProvider.TELEGRAM.value,
                ChannelConnection.status != "disabled",
                WorkspaceChannelConnection.tenant_id == principal.tenant_id,
                WorkspaceChannelConnection.workspace_id == principal.workspace_id,
            )
            .with_for_update()
        )
    ).all()
    matches = [
        connection
        for connection, scope in rows
        if (scope.agent_id is None or scope.agent_id == conversation.agent_id)
        and str((connection.configuration_json or {}).get("agentId") or "") == str(conversation.agent_id)
    ]
    if not matches:
        raise HTTPException(status_code=409, detail="Telegram is not connected for this agent")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple Telegram connections match this agent; disable the duplicate connection before replying",
        )
    connection = matches[0]
    try:
        credentials = (
            credential_store.decrypt(connection.credentials_encrypted)
            if connection.credentials_encrypted
            else {}
        )
    except CredentialStoreError as exc:
        raise HTTPException(status_code=409, detail="Telegram credentials require reconnection") from exc
    if not credentials.get("bot_token"):
        raise HTTPException(status_code=409, detail="Telegram bot token is not configured")
    if not credentials.get("webhook_secret"):
        raise HTTPException(status_code=409, detail="Telegram webhook secret is not configured")
    return connection, chat_id


@router.get("", response_model=PageResult[ConversationOut])
async def list_conversations(
    principal: ConversationsViewPrincipal,
    session: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    agent_id: UUID | None = Query(default=None),
    channel: Channel | None = Query(default=None),
    state: str | None = Query(default=None, max_length=40),
    search: str | None = Query(default=None, max_length=320),
) -> PageResult[ConversationOut]:
    conditions = [
        Conversation.tenant_id == principal.tenant_id,
        Conversation.workspace_id == principal.workspace_id,
    ]
    if principal.agent_ids is not None:
        conditions.append(Conversation.agent_id.in_(principal.agent_ids))
    if agent_id:
        conditions.append(Conversation.agent_id == agent_id)
    if channel:
        conditions.append(Conversation.channel == channel)
    if state:
        conditions.append(Conversation.state == state)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                Conversation.visitor_name.ilike(pattern),
                Conversation.visitor_email.ilike(pattern),
                Conversation.visitor_id.ilike(pattern),
            )
        )
    total = int(
        await session.scalar(select(func.count()).select_from(Conversation).where(*conditions)) or 0
    )
    rows = (
        await session.scalars(
            select(Conversation)
            .options(conversation_options())
            .where(*conditions)
            .order_by(Conversation.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return PageResult(
        items=[conversation_response(item) for item in rows], total=total, page=page, page_size=page_size
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: UUID, principal: ConversationsViewPrincipal, session: DB
) -> ConversationOut:
    conversation = await session.scalar(
        select(Conversation)
        .options(conversation_options())
        .where(*conversation_scope(principal, conversation_id))
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation_response(conversation)


@router.post("/{conversation_id}/resolve", response_model=ConversationOut)
async def resolve_conversation(
    conversation_id: UUID,
    principal: ConversationsResolvePrincipal,
    session: DB,
) -> ConversationOut:
    """Resolve a conversation and atomically create/finalize its linked Lead.

    The conversation and every message remain stored. Repeating this request is
    idempotent: it reconciles the existing Lead rather than creating another.
    """
    conversation = await locked_conversation(session, principal, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await conversation_resolution_service.resolve(
        session,
        conversation=conversation,
        actor_user_id=principal.user_id,
    )
    await session.commit()
    await session.refresh(conversation)
    return conversation_response(conversation)


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationPatch,
    principal: ConversationsResolvePrincipal,
    session: DB,
) -> ConversationOut:
    conversation = await locked_conversation(session, principal, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    previous_state = conversation.state
    patch = payload.model_dump(exclude_unset=True)
    requested_state = payload.state
    patch.pop("state", None)
    for name, value in patch.items():
        setattr(conversation, "unread_count" if name == "unread" else name, value)

    if requested_state == ConversationState.RESOLVED:
        await conversation_resolution_service.resolve(
            session,
            conversation=conversation,
            actor_user_id=principal.user_id,
        )
    elif requested_state is not None and requested_state != previous_state:
        conversation.state = requested_state
        conversation.ended_at = None
        event_payload = {
            "conversationId": str(conversation.id),
            "workspaceId": str(conversation.workspace_id),
            "agentId": str(conversation.agent_id),
            "previousState": previous_state.value,
            "state": requested_state.value,
        }
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="conversation",
            aggregate_id=conversation.id,
            event_type="conversation.state.changed.v1",
            payload=event_payload,
        )
        if previous_state == ConversationState.RESOLVED and requested_state == ConversationState.OPEN:
            enqueue_event(
                session,
                tenant_id=principal.tenant_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="conversation.reopened.v1",
                payload=event_payload,
            )

    await session.commit()
    await session.refresh(conversation)
    return conversation_response(conversation)


@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=201)
async def reply_to_conversation(
    conversation_id: UUID,
    payload: ConversationReplyCreate,
    principal: ConversationsReplyPrincipal,
    session: DB,
) -> MessageOut:
    conversation = await session.scalar(
        select(Conversation)
        .where(*conversation_scope(principal, conversation_id))
        .with_for_update()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    whatsapp_connection: WhatsAppConnection | None = None
    telegram_target: tuple[ChannelConnection, str] | None = None
    if conversation.channel == Channel.WHATSAPP:
        if not conversation.visitor_id or not conversation.visitor_id.isdigit():
            raise HTTPException(status_code=409, detail="WhatsApp recipient is unavailable")
        whatsapp_connection = await session.scalar(
            select(WhatsAppConnection)
            .where(
                WhatsAppConnection.tenant_id == principal.tenant_id,
                WhatsAppConnection.workspace_id == principal.workspace_id,
                WhatsAppConnection.agent_id == conversation.agent_id,
                WhatsAppConnection.status == "connected",
            )
            .with_for_update()
        )
        if not whatsapp_connection:
            raise HTTPException(status_code=409, detail="WhatsApp is not connected for this agent")
        if not token_expiry_is_current(whatsapp_connection.token_expires_at):
            raise HTTPException(
                status_code=409,
                detail="WhatsApp authorization expired; reconnect the integration",
            )
        latest_customer_message = await session.scalar(
            select(
                func.max(
                    func.coalesce(
                        WhatsAppInboundMessage.provider_timestamp,
                        WhatsAppInboundMessage.created_at,
                    )
                )
            ).where(
                WhatsAppInboundMessage.tenant_id == principal.tenant_id,
                WhatsAppInboundMessage.workspace_id == principal.workspace_id,
                WhatsAppInboundMessage.connection_id == whatsapp_connection.id,
                WhatsAppInboundMessage.conversation_id == conversation.id,
                WhatsAppInboundMessage.status.not_in(("ignored", "cancelled")),
                WhatsAppInboundMessage.message_text != "",
            )
        )
        if latest_customer_message is not None and latest_customer_message.tzinfo is None:
            latest_customer_message = latest_customer_message.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if (
            latest_customer_message is None
            or latest_customer_message < now - timedelta(hours=24)
            or latest_customer_message > now + timedelta(minutes=5)
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The 24-hour WhatsApp customer-service window is closed; "
                    "send an approved template instead"
                ),
            )
    else:
        telegram_target = await _telegram_connection_for_conversation(
            session,
            principal,
            conversation,
        )
    sequence = int(
        await session.scalar(
            select(func.coalesce(func.max(Message.sequence), 0)).where(
                Message.conversation_id == conversation.id,
                Message.tenant_id == principal.tenant_id,
            )
        )
        or 0
    )
    queued_external = whatsapp_connection is not None or telegram_target is not None
    message = Message(
        tenant_id=principal.tenant_id,
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        sequence=sequence + 1,
        role=MessageRole.AGENT,
        content=payload.content.strip(),
        finish_reason="queued" if queued_external else "sent",
    )
    session.add(message)
    conversation.updated_at = datetime.now(UTC)
    await session.flush()
    delivery: WhatsAppOutboundDelivery | None = None
    telegram_delivery: ChannelOutboundDelivery | None = None
    if whatsapp_connection:
        delivery = WhatsAppOutboundDelivery(
            tenant_id=principal.tenant_id,
            workspace_id=conversation.workspace_id,
            connection_id=whatsapp_connection.id,
            phone_number_id=whatsapp_connection.phone_number_id,
            message_id=message.id,
            recipient_wa_id=conversation.visitor_id or "",
            status="queued",
        )
        session.add(delivery)
        await session.flush()
    elif telegram_target:
        telegram_connection, chat_id = telegram_target
        telegram_delivery = ChannelOutboundDelivery(
            tenant_id=principal.tenant_id,
            workspace_id=conversation.workspace_id,
            connection_id=telegram_connection.id,
            message_id=message.id,
            provider=ChannelProvider.TELEGRAM.value,
            recipient_external_id=chat_id,
            status="queued",
        )
        session.add(telegram_delivery)
        await session.flush()
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="conversation",
        aggregate_id=conversation.id,
        event_type="chat.message.created.v1",
        payload={
            "conversationId": str(conversation.id),
            "workspaceId": str(conversation.workspace_id),
            "agentId": str(conversation.agent_id),
            "messageId": str(message.id),
            "role": "agent",
        },
    )
    await session.commit()
    if delivery:
        try:
            await asyncio.to_thread(
                send_whatsapp_human_reply.apply_async,
                args=[str(delivery.id)],
                queue="whatsapp.outbound",
                routing_key="whatsapp.outbound",
            )
            delivery.dispatch_attempts += 1
            delivery.dispatched_at = datetime.now(UTC)
            delivery.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
            delivery.last_error = None
        except Exception:
            # The durable dispatcher will retry this database-backed delivery.
            delivery.dispatch_attempts += 1
            exhausted = delivery.dispatch_attempts >= get_settings().whatsapp_dispatch_max_attempts
            delivery.status = "dispatch_failed" if exhausted else "failed"
            delivery.next_dispatch_at = None if exhausted else datetime.now(UTC)
            delivery.last_error = "queue dispatch unavailable"
        await session.commit()
    elif telegram_delivery:
        try:
            await asyncio.to_thread(
                send_telegram_message.apply_async,
                args=[str(telegram_delivery.id)],
                queue="telegram.outbound",
                routing_key="telegram.outbound",
            )
            telegram_delivery.dispatch_attempts += 1
            telegram_delivery.dispatched_at = datetime.now(UTC)
            telegram_delivery.next_dispatch_at = datetime.now(UTC) + timedelta(minutes=5)
            telegram_delivery.last_error = None
        except Exception:
            # The durable dispatcher will retry this database-backed delivery.
            telegram_delivery.dispatch_attempts += 1
            telegram_delivery.status = "failed"
            telegram_delivery.next_dispatch_at = datetime.now(UTC)
            telegram_delivery.last_error = "queue dispatch unavailable"
        await session.commit()
    await session.refresh(message)
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        citations=[],
    )
