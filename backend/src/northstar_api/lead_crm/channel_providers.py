from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from northstar_api.lead_crm.channels import (
    CanonicalInboundEvent,
    CanonicalMessage,
    CanonicalSender,
    ChannelConnectionContext,
    ChannelConnector,
    channel_registry,
)
from northstar_api.lead_crm.domain import ChannelProvider


def _timestamp_seconds(value: object) -> datetime | None:
    try:
        raw = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if raw > 10_000_000_000:
        raw /= 1000
    try:
        return datetime.fromtimestamp(raw, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


class MetaMessagingConnector(ChannelConnector):
    def __init__(self, provider: ChannelProvider) -> None:
        self.provider = provider

    async def verify(
        self,
        context: ChannelConnectionContext,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        secret = str(context.credentials.get("app_secret") or "")
        signature = headers.get("x-hub-signature-256", "")
        if not secret or not signature.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return _constant_time_equal(signature, expected)

    async def normalize(
        self,
        context: ChannelConnectionContext,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        received_at: datetime,
        raw_event_id: uuid.UUID | None = None,
    ) -> list[CanonicalInboundEvent]:
        output: list[CanonicalInboundEvent] = []
        entries = payload.get("entry")
        if not isinstance(entries, list):
            return output
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id") or "")
            messaging = entry.get("messaging")
            if isinstance(messaging, list):
                for index, item in enumerate(messaging):
                    if not isinstance(item, dict):
                        continue
                    sender = item.get("sender") if isinstance(item.get("sender"), dict) else {}
                    message = item.get("message") if isinstance(item.get("message"), dict) else {}
                    message_id = str(message.get("mid") or "") or None
                    event_id = (
                        message_id or f"{entry_id}:{item.get('timestamp') or received_at.timestamp()}:{index}"
                    )
                    output.append(
                        CanonicalInboundEvent(
                            event_id=uuid.uuid4(),
                            tenant_id=context.tenant_id,
                            provider=self.provider,
                            connection_key=str(context.connection_id),
                            external_event_id=event_id,
                            event_type="message.received",
                            sender=CanonicalSender(external_id=str(sender.get("id") or "") or None),
                            message=CanonicalMessage(
                                external_message_id=message_id,
                                message_type="text"
                                if isinstance(message.get("text"), str)
                                else str(message.get("type") or "unknown"),
                                text=str(message.get("text"))
                                if isinstance(message.get("text"), str)
                                else None,
                                provider_timestamp=_timestamp_seconds(item.get("timestamp")),
                            ),
                            correlation_id=correlation_id,
                            received_at=received_at,
                            conversation_reference=str(sender.get("id") or "") or None,
                            raw_event_id=raw_event_id,
                            metadata={"entryId": entry_id, "recipient": item.get("recipient")},
                        )
                    )
            changes = entry.get("changes")
            if isinstance(changes, list):
                for index, change in enumerate(changes):
                    if not isinstance(change, dict):
                        continue
                    value = change.get("value") if isinstance(change.get("value"), dict) else {}
                    messages = value.get("messages") if isinstance(value, dict) else None
                    contacts = value.get("contacts") if isinstance(value, dict) else None
                    contact_name = None
                    if isinstance(contacts, list) and contacts and isinstance(contacts[0], dict):
                        profile = contacts[0].get("profile")
                        if isinstance(profile, dict):
                            contact_name = profile.get("name")
                    if not isinstance(messages, list):
                        continue
                    for message_index, message in enumerate(messages):
                        if not isinstance(message, dict):
                            continue
                        sender_id = str(message.get("from") or "") or None
                        external_id = (
                            str(message.get("id") or "") or f"{entry_id}:change:{index}:{message_index}"
                        )
                        text_value = message.get("text") if isinstance(message.get("text"), dict) else {}
                        output.append(
                            CanonicalInboundEvent(
                                event_id=uuid.uuid4(),
                                tenant_id=context.tenant_id,
                                provider=self.provider,
                                connection_key=str(context.connection_id),
                                external_event_id=external_id,
                                event_type="message.received",
                                sender=CanonicalSender(
                                    external_id=sender_id,
                                    name=str(contact_name) if contact_name else None,
                                    phone=sender_id if self.provider == ChannelProvider.WHATSAPP else None,
                                ),
                                message=CanonicalMessage(
                                    external_message_id=str(message.get("id") or "") or None,
                                    message_type=str(message.get("type") or "unknown"),
                                    text=str(text_value.get("body"))
                                    if text_value.get("body") is not None
                                    else None,
                                    provider_timestamp=_timestamp_seconds(message.get("timestamp")),
                                ),
                                correlation_id=correlation_id,
                                received_at=received_at,
                                conversation_reference=sender_id,
                                raw_event_id=raw_event_id,
                                metadata={"entryId": entry_id, "field": change.get("field")},
                            )
                        )
        return output


class TelegramConnector(ChannelConnector):
    provider = ChannelProvider.TELEGRAM

    async def verify(
        self,
        context: ChannelConnectionContext,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        expected = str(context.credentials.get("webhook_secret") or "")
        supplied = headers.get("x-telegram-bot-api-secret-token", "")
        return bool(expected and supplied and _constant_time_equal(expected, supplied))

    async def normalize(
        self,
        context: ChannelConnectionContext,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        received_at: datetime,
        raw_event_id: uuid.UUID | None = None,
    ) -> list[CanonicalInboundEvent]:
        update_id = payload.get("update_id")
        message = payload.get("message") or payload.get("edited_message") or payload.get("business_message")
        if update_id is None or not isinstance(message, dict):
            return []
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        text = message.get("text") or message.get("caption")
        sender_name = (
            " ".join(
                part
                for part in (
                    str(sender.get("first_name") or "").strip(),
                    str(sender.get("last_name") or "").strip(),
                )
                if part
            )
            or None
        )
        message_id = message.get("message_id")
        return [
            CanonicalInboundEvent(
                event_id=uuid.uuid4(),
                tenant_id=context.tenant_id,
                provider=self.provider,
                connection_key=str(context.connection_id),
                external_event_id=str(update_id),
                event_type="message.received",
                sender=CanonicalSender(external_id=str(sender.get("id") or "") or None, name=sender_name),
                message=CanonicalMessage(
                    external_message_id=str(message_id) if message_id is not None else None,
                    message_type="text" if text is not None else "unknown",
                    text=str(text) if text is not None else None,
                    provider_timestamp=_timestamp_seconds(message.get("date")),
                ),
                correlation_id=correlation_id,
                received_at=received_at,
                conversation_reference=str(chat.get("id") or "") or None,
                raw_event_id=raw_event_id,
                metadata={"chatType": chat.get("type"), "username": sender.get("username")},
            )
        ]

    async def health_check(self, context: ChannelConnectionContext) -> dict[str, str]:
        return {
            "status": "healthy"
            if context.credentials.get("bot_token") and context.credentials.get("webhook_secret")
            else "configuration_error"
        }


class SignedAPIConnector(ChannelConnector):
    def __init__(self, provider: ChannelProvider) -> None:
        self.provider = provider

    async def verify(
        self,
        context: ChannelConnectionContext,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        secret = str(context.credentials.get("webhook_secret") or "")
        if not secret:
            return bool(context.configuration.get("allowUnsigned", False))
        supplied = headers.get("x-northstar-signature", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return bool(supplied and _constant_time_equal(expected, supplied))

    async def normalize(
        self,
        context: ChannelConnectionContext,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        received_at: datetime,
        raw_event_id: uuid.UUID | None = None,
    ) -> list[CanonicalInboundEvent]:
        external_event_id = str(payload.get("eventId") or payload.get("event_id") or "")
        if not external_event_id:
            stable = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()
            external_event_id = hashlib.sha256(stable).hexdigest()
        sender = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        message_text = message.get("text") if message else payload.get("messageText")
        timestamp = (
            payload.get("timestamp") or message.get("timestamp") if isinstance(message, dict) else None
        )
        return [
            CanonicalInboundEvent(
                event_id=uuid.uuid4(),
                tenant_id=context.tenant_id,
                provider=self.provider,
                connection_key=str(context.connection_id),
                external_event_id=external_event_id,
                event_type=str(payload.get("eventType") or "message.received"),
                sender=CanonicalSender(
                    external_id=str(sender.get("externalId") or sender.get("id") or "") or None,
                    name=str(sender.get("name") or "") or None,
                    phone=str(sender.get("phone") or "") or None,
                    email=str(sender.get("email") or "") or None,
                ),
                message=CanonicalMessage(
                    external_message_id=str(message.get("id") or "") or None,
                    message_type=str(message.get("type") or "text"),
                    text=str(message_text) if message_text is not None else None,
                    provider_timestamp=_timestamp_seconds(timestamp),
                ),
                correlation_id=correlation_id,
                received_at=received_at,
                conversation_reference=str(payload.get("conversationId") or "") or None,
                campaign_attribution=dict(payload.get("campaign") or {})
                if isinstance(payload.get("campaign"), dict)
                else {},
                raw_event_id=raw_event_id,
                metadata=dict(payload.get("metadata") or {})
                if isinstance(payload.get("metadata"), dict)
                else {},
            )
        ]


def register_default_channel_connectors() -> None:
    connectors: tuple[ChannelConnector, ...] = (
        MetaMessagingConnector(ChannelProvider.WHATSAPP),
        MetaMessagingConnector(ChannelProvider.INSTAGRAM),
        MetaMessagingConnector(ChannelProvider.FACEBOOK_MESSENGER),
        TelegramConnector(),
        SignedAPIConnector(ChannelProvider.API),
        SignedAPIConnector(ChannelProvider.CUSTOM),
        SignedAPIConnector(ChannelProvider.WIDGET),
        SignedAPIConnector(ChannelProvider.SLACK),
    )
    registered = set(channel_registry._connectors)
    for connector in connectors:
        if connector.provider not in registered:
            channel_registry.register(connector)
            registered.add(connector.provider)
