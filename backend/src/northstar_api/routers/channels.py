from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session, set_tenant_context
from northstar_api.dependencies import AdminPrincipal, CurrentPrincipal
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channels import ChannelConnectionContext, channel_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.services.outbox import enqueue_event

router = APIRouter(tags=["channels"])
DB = Annotated[AsyncSession, Depends(get_session)]
MAX_WEBHOOK_BYTES = 1_048_576


class ChannelConnectionCreate(BaseModel):
    provider: ChannelProvider
    name: str = Field(min_length=1, max_length=160)
    configuration: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] = Field(default_factory=dict)


class ChannelConnectionOut(BaseModel):
    id: UUID
    public_id: str
    provider: str
    name: str
    status: str
    configuration: dict[str, Any]
    last_health_at: datetime | None
    last_event_at: datetime | None
    last_failure_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


def _out(value: ChannelConnection) -> ChannelConnectionOut:
    return ChannelConnectionOut(
        id=value.id,
        public_id=value.public_id,
        provider=value.provider,
        name=value.name,
        status=value.status,
        configuration=value.configuration_json,
        last_health_at=value.last_health_at,
        last_event_at=value.last_event_at,
        last_failure_at=value.last_failure_at,
        last_error=value.last_error,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _credentials(value: ChannelConnection) -> dict[str, Any]:
    if not value.credentials_encrypted:
        return {}
    try:
        return credential_store.decrypt(value.credentials_encrypted)
    except CredentialStoreError as exc:
        raise HTTPException(status_code=409, detail="Channel credentials require reconnection") from exc


def _context(value: ChannelConnection, credentials: dict[str, Any]) -> ChannelConnectionContext:
    return ChannelConnectionContext(
        tenant_id=value.tenant_id,
        connection_id=value.id,
        provider=ChannelProvider(value.provider),
        configuration=value.configuration_json,
        credentials=credentials,
    )


@router.get("/channels/providers")
async def channel_providers(_: CurrentPrincipal) -> list[dict[str, Any]]:
    registered = set(channel_registry.providers())
    return [
        {
            "id": provider.value,
            "name": provider.value.replace("_", " ").title(),
            "runtimeRegistered": provider in registered,
        }
        for provider in ChannelProvider
    ]


@router.post("/channels/connections", response_model=ChannelConnectionOut, status_code=201)
async def create_channel_connection(
    payload: ChannelConnectionCreate,
    principal: AdminPrincipal,
    session: DB,
) -> ChannelConnectionOut:
    duplicate = await session.scalar(
        select(ChannelConnection.id).where(
            ChannelConnection.tenant_id == principal.tenant_id,
            ChannelConnection.name == payload.name,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A channel connection with that name already exists")
    try:
        channel_registry.get(payload.provider)
    except KeyError as exc:
        raise HTTPException(
            status_code=409, detail="Channel connector is not available in this runtime"
        ) from exc
    encrypted = None
    if payload.credentials:
        try:
            encrypted = credential_store.encrypt(payload.credentials)
        except CredentialStoreError as exc:
            raise HTTPException(status_code=503, detail="Credential encryption is not configured") from exc
    value = ChannelConnection(
        tenant_id=principal.tenant_id,
        public_id=f"chn_{uuid.uuid4().hex}",
        provider=payload.provider.value,
        name=payload.name,
        status="configured" if encrypted or payload.configuration else "draft",
        credentials_encrypted=encrypted,
        configuration_json=payload.configuration,
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return _out(value)


@router.get("/channels/connections", response_model=list[ChannelConnectionOut])
async def list_channel_connections(
    principal: CurrentPrincipal,
    session: DB,
) -> list[ChannelConnectionOut]:
    values = list(
        await session.scalars(
            select(ChannelConnection)
            .where(ChannelConnection.tenant_id == principal.tenant_id)
            .order_by(ChannelConnection.created_at.desc())
        )
    )
    return [_out(value) for value in values]


@router.post("/channels/connections/{connection_id}/test")
async def test_channel_connection(
    connection_id: UUID,
    principal: AdminPrincipal,
    session: DB,
) -> dict[str, Any]:
    value = await session.scalar(
        select(ChannelConnection).where(
            ChannelConnection.id == connection_id,
            ChannelConnection.tenant_id == principal.tenant_id,
        )
    )
    if not value:
        raise HTTPException(status_code=404, detail="Channel connection not found")
    credentials = _credentials(value)
    connector = channel_registry.get(ChannelProvider(value.provider))
    result = await connector.health_check(_context(value, credentials))
    value.last_health_at = datetime.now(UTC)
    value.status = result.get("status", "unknown")
    value.last_error = None if value.status == "healthy" else "Channel health validation failed"
    await session.commit()
    return result


@router.delete("/channels/connections/{connection_id}", status_code=204)
async def disable_channel_connection(
    connection_id: UUID,
    principal: AdminPrincipal,
    session: DB,
) -> None:
    value = await session.scalar(
        select(ChannelConnection).where(
            ChannelConnection.id == connection_id,
            ChannelConnection.tenant_id == principal.tenant_id,
        )
    )
    if not value:
        raise HTTPException(status_code=404, detail="Channel connection not found")
    value.status = "disabled"
    value.credentials_encrypted = None
    value.credentials_ref = None
    await session.commit()


@router.get("/webhooks/channels/{tenant_id}/{provider}/{public_id}", include_in_schema=False)
async def verify_meta_channel_webhook(
    tenant_id: UUID,
    provider: ChannelProvider,
    public_id: str,
    session: DB,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    if provider not in {
        ChannelProvider.WHATSAPP,
        ChannelProvider.INSTAGRAM,
        ChannelProvider.FACEBOOK_MESSENGER,
    }:
        raise HTTPException(status_code=404, detail="Webhook verification is not supported")
    await set_tenant_context(session, tenant_id)
    value = await session.scalar(
        select(ChannelConnection).where(
            ChannelConnection.tenant_id == tenant_id,
            ChannelConnection.public_id == public_id,
            ChannelConnection.provider == provider.value,
            ChannelConnection.status != "disabled",
        )
    )
    if not value:
        raise HTTPException(status_code=404, detail="Channel connection not found")
    credentials = _credentials(value)
    expected = str(credentials.get("verify_token") or "")
    if (
        hub_mode != "subscribe"
        or not expected
        or not hub_verify_token
        or not hmac.compare_digest(expected.encode(), hub_verify_token.encode())
        or hub_challenge is None
    ):
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/webhooks/channels/{tenant_id}/{provider}/{public_id}", include_in_schema=False)
async def receive_channel_webhook(
    tenant_id: UUID,
    provider: ChannelProvider,
    public_id: str,
    request: Request,
    session: DB,
) -> dict[str, Any]:
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload is too large")
    try:
        payload = orjson.loads(body)
    except orjson.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Webhook payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    await set_tenant_context(session, tenant_id)
    connection = await session.scalar(
        select(ChannelConnection).where(
            ChannelConnection.tenant_id == tenant_id,
            ChannelConnection.public_id == public_id,
            ChannelConnection.provider == provider.value,
            ChannelConnection.status != "disabled",
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Channel connection not found")
    credentials = _credentials(connection)
    connector = channel_registry.get(provider)
    headers = {key.lower(): value for key, value in request.headers.items()}
    if not await connector.verify(_context(connection, credentials), headers=headers, body=body):
        connection.last_failure_at = datetime.now(UTC)
        connection.last_error = "Webhook signature/secret verification failed"
        await session.commit()
        raise HTTPException(status_code=401, detail="Webhook verification failed")

    correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    received_at = datetime.now(UTC)
    normalized = await connector.normalize(
        _context(connection, credentials),
        payload=payload,
        correlation_id=correlation_id,
        received_at=received_at,
    )
    if not normalized:
        fallback_id = hashlib.sha256(body).hexdigest()
        external_ids = [(fallback_id, "provider.notification")]
    else:
        external_ids = [(event.external_event_id, event.event_type) for event in normalized]

    stored = 0
    for external_id, event_type in external_ids:
        existing = await session.scalar(
            select(RawWebhookEvent.id).where(
                RawWebhookEvent.tenant_id == tenant_id,
                RawWebhookEvent.provider == provider.value,
                RawWebhookEvent.connection_key == str(connection.id),
                RawWebhookEvent.external_event_id == external_id,
            )
        )
        if existing:
            continue
        raw_event = RawWebhookEvent(
            tenant_id=tenant_id,
            connection_key=str(connection.id),
            provider=provider.value,
            external_event_id=external_id,
            event_type=event_type,
            payload_json=payload,
            headers_json={
                "content-type": request.headers.get("content-type"),
                "user-agent": request.headers.get("user-agent"),
            },
            payload_hash=hashlib.sha256(body).hexdigest(),
            verification_status="verified",
            processing_status="received",
            received_at=received_at,
            correlation_id=correlation_id,
        )
        try:
            async with session.begin_nested():
                session.add(raw_event)
                await session.flush()
        except IntegrityError:
            continue
        enqueue_event(
            session,
            tenant_id=tenant_id,
            aggregate_type="raw_webhook_event",
            aggregate_id=raw_event.id,
            event_type="channel.event.received.v1",
            payload={"rawEventId": str(raw_event.id), "provider": provider.value},
        )
        stored += 1

    connection.last_event_at = received_at
    connection.status = "healthy"
    connection.last_error = None
    await session.commit()
    return {
        "acknowledged": True,
        "acceptedEvents": stored,
        "correlationId": correlation_id,
    }
