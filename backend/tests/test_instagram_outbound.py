from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import AsyncClient

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.channel_models import ChannelConnection, ChannelOutboundDelivery
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
from northstar_api.lead_crm.credentials import credential_store
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Agent, Channel, Conversation, Message, MessageRole
from northstar_api.services.instagram import (
    InstagramAPIError,
    InstagramMessagingClient,
    normalize_instagram_api_version,
)
from northstar_api.workers.celery_app import celery_app
from northstar_api.workers.event_utils import EventEnvelope
from northstar_api.workers.instagram_outbound_consumer import (
    instagram_recipient_id,
    project_instagram_delivery,
)
from northstar_api.workers.instagram_tasks import instagram_thread_lock_key


def test_instagram_api_version_normalization() -> None:
    assert normalize_instagram_api_version("v26.0") == "v26.0"
    assert normalize_instagram_api_version("26.0") == "v26.0"
    with pytest.raises(InstagramAPIError):
        normalize_instagram_api_version("latest")


def test_instagram_conversation_identity_is_provider_exact() -> None:
    conversation = Conversation(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        visitor_id="instagram:17841400000000000",
        visitor_name="Instagram user",
        channel=Channel.API,
    )
    assert instagram_recipient_id(conversation) == "17841400000000000"
    conversation.visitor_id = "facebook_messenger:17841400000000000"
    assert instagram_recipient_id(conversation) is None
    conversation.visitor_id = "instagram:"
    assert instagram_recipient_id(conversation) is None


def test_instagram_lock_and_queue_are_provider_scoped() -> None:
    connection_id = uuid4()
    first = instagram_thread_lock_key(connection_id, "100")
    assert first == instagram_thread_lock_key(connection_id, "100")
    assert first != instagram_thread_lock_key(connection_id, "101")
    assert first != instagram_thread_lock_key(uuid4(), "100")
    route = celery_app.conf.task_routes["northstar.send_instagram_message"]
    assert route == {"queue": "instagram.outbound", "routing_key": "instagram.outbound"}
    queue_names = {queue.name for queue in celery_app.conf.task_queues}
    assert {"instagram.outbound", "instagram.failed", "telegram.outbound", "whatsapp.outbound"} <= queue_names


@pytest.mark.anyio
async def test_instagram_client_sends_text_with_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str],
            json: object,
        ) -> httpx.Response:
            assert method == "POST"
            assert url == "https://graph.instagram.com/v26.0/me/messages"
            assert headers["Authorization"] == "Bearer ig-access-token"
            assert json == {
                "recipient": {"id": "17841400000000000"},
                "message": {"text": "Hello from Northstar"},
            }
            return httpx.Response(200, json={"message_id": "mid.123"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    value = await InstagramMessagingClient().send_text(
        "ig-access-token",
        recipient_id="17841400000000000",
        text="Hello from Northstar",
        api_version="v26.0",
    )
    assert value == "mid.123"


@pytest.mark.anyio
async def test_instagram_client_classifies_auth_and_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        httpx.Response(400, json={"error": {"message": "Invalid OAuth access token", "code": 190}}),
        httpx.Response(
            429,
            headers={"Retry-After": "8"},
            json={"error": {"message": "Application request limit reached", "code": 4}},
        ),
    ]

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, *args: object, **kwargs: object) -> httpx.Response:
            return responses.pop(0)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = InstagramMessagingClient()
    with pytest.raises(InstagramAPIError) as auth_error:
        await client.get_me("bad-token", api_version="v26.0")
    assert auth_error.value.requires_reconnect is True
    assert auth_error.value.retryable is False

    with pytest.raises(InstagramAPIError) as rate_error:
        await client.send_text(
            "token",
            recipient_id="17841400000000000",
            text="hello",
            api_version="26.0",
        )
    assert rate_error.value.retryable is True
    assert rate_error.value.retry_after_seconds == 8


async def _workspace_scope(client: AsyncClient, auth_headers: dict[str, str]) -> tuple[UUID, UUID]:
    response = await client.get("/api/v1/workspace", headers=auth_headers)
    assert response.status_code == 200, response.text
    return UUID(response.json()["tenantId"]), UUID(response.json()["id"])


@pytest.mark.anyio
async def test_projection_is_durable_idempotent_and_does_not_change_non_instagram(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRM_CREDENTIAL_ENCRYPTION_KEY", "instagram-outbound-test-key")
    tenant_id, workspace_id = await _workspace_scope(client, auth_headers)
    agent_id = uuid4()
    instagram_conversation_id = uuid4()
    api_conversation_id = uuid4()
    instagram_message_id = uuid4()
    api_message_id = uuid4()
    connection_id = uuid4()

    async with SessionFactory() as session:
        session.add(Agent(id=agent_id, tenant_id=tenant_id, workspace_id=workspace_id, name="Instagram runtime"))
        session.add_all(
            [
                Conversation(
                    id=instagram_conversation_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    visitor_id="instagram:17841400000000000",
                    visitor_name="Instagram customer",
                    channel=Channel.API,
                ),
                Conversation(
                    id=api_conversation_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    visitor_id="api:ordinary-client",
                    visitor_name="API customer",
                    channel=Channel.API,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                Message(
                    id=instagram_message_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    conversation_id=instagram_conversation_id,
                    sequence=1,
                    role=MessageRole.AGENT,
                    content="Instagram reply",
                    finish_reason="sent",
                ),
                Message(
                    id=api_message_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    conversation_id=api_conversation_id,
                    sequence=1,
                    role=MessageRole.AGENT,
                    content="API reply",
                    finish_reason="sent",
                ),
                ChannelConnection(
                    id=connection_id,
                    tenant_id=tenant_id,
                    public_id=f"chn_{uuid4().hex}",
                    provider=ChannelProvider.INSTAGRAM.value,
                    name=f"Instagram {uuid4().hex[:8]}",
                    status="configured",
                    credentials_encrypted=credential_store.encrypt(
                        {"access_token": "ig-token", "app_secret": "app-secret", "verify_token": "verify-token"}
                    ),
                    configuration_json={"agentId": str(agent_id), "apiVersion": "v26.0"},
                ),
            ]
        )
        await session.flush()
        session.add(
            WorkspaceChannelConnection(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
            )
        )
        await session.commit()

    def event(conversation_id: UUID, message_id: UUID) -> EventEnvelope:
        return EventEnvelope(
            event_id=uuid4(),
            event_type="chat.message.created.v1",
            tenant_id=tenant_id,
            occurred_at=datetime.now(UTC),
            payload={
                "conversationId": str(conversation_id),
                "workspaceId": str(workspace_id),
                "agentId": str(agent_id),
                "messageId": str(message_id),
                "role": "agent",
            },
        )

    instagram_event = event(instagram_conversation_id, instagram_message_id)
    async with SessionFactory() as session:
        first = await project_instagram_delivery(session, instagram_event)
        assert first is not None
        await session.commit()
        first_id = first.id
    async with SessionFactory() as session:
        second = await project_instagram_delivery(session, instagram_event)
        assert second is not None and second.id == first_id
        message = await session.get(Message, instagram_message_id)
        delivery = await session.get(ChannelOutboundDelivery, first_id)
        assert message is not None and message.finish_reason == "queued"
        assert delivery is not None
        assert delivery.provider == ChannelProvider.INSTAGRAM.value
        assert delivery.recipient_external_id == "17841400000000000"
        assert delivery.connection_id == connection_id

    async with SessionFactory() as session:
        assert await project_instagram_delivery(session, event(api_conversation_id, api_message_id)) is None
        api_message = await session.get(Message, api_message_id)
        assert api_message is not None and api_message.finish_reason == "sent"
