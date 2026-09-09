from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.models import Agent, Channel, Conversation, Lead, Message, MessageRole


async def test_resolve_creates_one_lead_and_preserves_conversation(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    created_agent = await client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "name": "Resolution Lead Test Agent",
            "description": "Validates resolved conversation lead finalization",
        },
    )
    assert created_agent.status_code == 201, created_agent.text
    agent_payload = created_agent.json()

    async with SessionFactory() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == UUID(agent_payload["id"])))
        assert agent is not None
        conversation = Conversation(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            visitor_id="visitor-resolution-test",
            visitor_name="Rahul Kumar",
            visitor_email="rahul@example.com",
            channel=Channel.WIDGET,
        )
        session.add(conversation)
        await session.flush()
        session.add(
            Message(
                tenant_id=agent.tenant_id,
                workspace_id=agent.workspace_id,
                conversation_id=conversation.id,
                sequence=1,
                role=MessageRole.USER,
                content="I want course details and a callback.",
            )
        )
        await session.commit()
        conversation_id = str(conversation.id)
        workspace_id = str(agent.workspace_id)

    headers = {**auth_headers, "X-Workspace-ID": workspace_id}

    first_resolution = await client.post(
        f"/api/v1/conversations/{conversation_id}/resolve",
        headers=headers,
    )
    assert first_resolution.status_code == 200, first_resolution.text
    resolved = first_resolution.json()
    assert resolved["state"] == "resolved"
    assert len(resolved["messages"]) == 1
    assert resolved["messages"][0]["content"] == "I want course details and a callback."

    leads_response = await client.get(
        "/api/v1/leads",
        headers=headers,
        params={"agent_id": agent_payload["id"]},
    )
    assert leads_response.status_code == 200, leads_response.text
    linked_leads = [
        lead for lead in leads_response.json()["items"] if lead["conversationId"] == conversation_id
    ]
    assert len(linked_leads) == 1
    lead_id = linked_leads[0]["id"]
    assert linked_leads[0]["name"] == "Rahul Kumar"
    assert linked_leads[0]["email"] == "rahul@example.com"
    assert linked_leads[0]["fields"]["sourceChannel"] == "widget"

    second_resolution = await client.post(
        f"/api/v1/conversations/{conversation_id}/resolve",
        headers=headers,
    )
    assert second_resolution.status_code == 200, second_resolution.text

    leads_after_retry = await client.get(
        "/api/v1/leads",
        headers=headers,
        params={"agent_id": agent_payload["id"]},
    )
    linked_after_retry = [
        lead
        for lead in leads_after_retry.json()["items"]
        if lead["conversationId"] == conversation_id
    ]
    assert [lead["id"] for lead in linked_after_retry] == [lead_id]

    reopened = await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        headers=headers,
        json={"state": "open"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["state"] == "open"
    assert len(reopened.json()["messages"]) == 1

    async with SessionFactory() as session:
        persisted_leads = (
            await session.scalars(
                select(Lead).where(Lead.conversation_id == UUID(conversation_id))
            )
        ).all()
        assert len(persisted_leads) == 1
        assert str(persisted_leads[0].id) == lead_id
