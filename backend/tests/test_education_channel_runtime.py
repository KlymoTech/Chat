from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channels import CanonicalInboundEvent, CanonicalMessage, CanonicalSender
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.lead_crm.models import RawWebhookEvent
from northstar_api.models import Agent, Conversation, Lead, Message, OutboxEvent
from northstar_api.workers.channel_event_consumer import _process_education_message


async def _seed_authorized_student(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> tuple[dict, dict[str, str]]:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    headers = {**auth_headers, "X-Workspace-ID": workspace.json()["id"]}

    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": "CHANNEL-AUTH", "name": "Channel Authorization Course"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": "CHANNEL-AUTH-A",
            "name": "Channel Authorization Batch",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert batch.status_code == 201, batch.text
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={"studentNumber": "CHANNEL-1001", "name": "Channel Student"},
    )
    assert student.status_code == 201, student.text
    identity = await client.post(
        f"/api/v1/education/students/{student.json()['id']}/identities",
        headers=headers,
        json={
            "identityType": "whatsapp",
            "identifier": "+919876540101",
            "status": "verified",
        },
    )
    assert identity.status_code == 201, identity.text
    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "Channel Runtime Education Agent",
            "description": "Education channel runtime integration test",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent.status_code == 201, agent.text
    enrollment = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student.json()["id"],
            "courseId": course.json()["id"],
            "batchId": batch.json()["id"],
            "agentId": agent.json()["id"],
            "status": "active",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert enrollment.status_code == 201, enrollment.text
    activated = await client.patch(
        f"/api/v1/agents/{agent.json()['id']}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text
    return {
        "workspaceId": workspace.json()["id"],
        "agentId": agent.json()["id"],
        "studentId": student.json()["id"],
        "enrollmentId": enrollment.json()["id"],
        "courseId": course.json()["id"],
        "batchId": batch.json()["id"],
    }, headers


def _canonical(
    *,
    tenant_id: uuid.UUID,
    connection_id: uuid.UUID,
    phone: str,
    external_event_id: str,
) -> CanonicalInboundEvent:
    return CanonicalInboundEvent(
        event_id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider=ChannelProvider.WHATSAPP,
        connection_key=str(connection_id),
        external_event_id=external_event_id,
        event_type="message.received",
        sender=CanonicalSender(
            external_id=phone.removeprefix("+"),
            name="Education Student",
            phone=phone.removeprefix("+"),
        ),
        message=CanonicalMessage(
            external_message_id=f"msg-{external_event_id}",
            message_type="text",
            text="Explain this course topic.",
            provider_timestamp=datetime.now(UTC),
        ),
        correlation_id=f"correlation-{external_event_id}",
        received_at=datetime.now(UTC),
        conversation_reference=phone.removeprefix("+"),
    )


async def _raw_event(
    session,
    *,
    tenant_id: uuid.UUID,
    connection_id: uuid.UUID,
    external_event_id: str,
) -> RawWebhookEvent:
    payload = {"externalEventId": external_event_id}
    raw = RawWebhookEvent(
        tenant_id=tenant_id,
        connection_key=str(connection_id),
        provider=ChannelProvider.WHATSAPP.value,
        external_event_id=external_event_id,
        event_type="message.received",
        payload_json=payload,
        headers_json={},
        payload_hash=hashlib.sha256(str(payload).encode()).hexdigest(),
        verification_status="verified",
        processing_status="received",
        correlation_id=f"correlation-{external_event_id}",
        received_at=datetime.now(UTC),
    )
    session.add(raw)
    await session.flush()
    return raw


async def test_education_channel_runtime_never_enters_lead_path(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, _ = await _seed_authorized_student(client, auth_headers)

    async with SessionFactory() as session:
        agent = await session.scalar(
            select(Agent).where(Agent.id == uuid.UUID(seeded["agentId"]))
        )
        assert agent is not None
        connection = ChannelConnection(
            tenant_id=agent.tenant_id,
            provider=ChannelProvider.WHATSAPP.value,
            name=f"Education runtime {uuid.uuid4().hex}",
            status="healthy",
            configuration_json={"agentId": str(agent.id)},
        )
        session.add(connection)
        await session.flush()

        authorized_raw = await _raw_event(
            session,
            tenant_id=agent.tenant_id,
            connection_id=connection.id,
            external_event_id="education-authorized",
        )
        await _process_education_message(
            session,
            raw=authorized_raw,
            connection=connection,
            canonical=_canonical(
                tenant_id=agent.tenant_id,
                connection_id=connection.id,
                phone="+919876540101",
                external_event_id="education-authorized",
            ),
            agent=agent,
        )

        conversation_count = int(
            await session.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.workspace_id == agent.workspace_id,
                    Conversation.agent_id == agent.id,
                )
            )
            or 0
        )
        message_count = int(
            await session.scalar(
                select(func.count(Message.id))
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(Conversation.agent_id == agent.id)
            )
            or 0
        )
        lead_count = int(
            await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.workspace_id == agent.workspace_id,
                    Lead.agent_id == agent.id,
                )
            )
            or 0
        )
        authorized_event = await session.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == agent.tenant_id,
                OutboxEvent.event_type == "education.access.authorized.v1",
            )
            .order_by(OutboxEvent.created_at.desc())
        )
        assert conversation_count == 1
        assert message_count == 1
        assert lead_count == 0
        assert authorized_event is not None
        assert authorized_event.payload["authorized"] is True
        assert authorized_event.payload["studentId"] == seeded["studentId"]
        assert authorized_event.payload["enrollmentId"] == seeded["enrollmentId"]
        assert authorized_event.payload["courseId"] == seeded["courseId"]
        assert authorized_event.payload["batchId"] == seeded["batchId"]
        assert authorized_raw.processing_status == "processed"

        denied_raw = await _raw_event(
            session,
            tenant_id=agent.tenant_id,
            connection_id=connection.id,
            external_event_id="education-denied",
        )
        await _process_education_message(
            session,
            raw=denied_raw,
            connection=connection,
            canonical=_canonical(
                tenant_id=agent.tenant_id,
                connection_id=connection.id,
                phone="+919876549999",
                external_event_id="education-denied",
            ),
            agent=agent,
        )

        conversations_after_denial = int(
            await session.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.workspace_id == agent.workspace_id,
                    Conversation.agent_id == agent.id,
                )
            )
            or 0
        )
        leads_after_denial = int(
            await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.workspace_id == agent.workspace_id,
                    Lead.agent_id == agent.id,
                )
            )
            or 0
        )
        denied_event = await session.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == agent.tenant_id,
                OutboxEvent.event_type == "education.access.denied.v1",
            )
            .order_by(OutboxEvent.created_at.desc())
        )
        assert conversations_after_denial == 1
        assert leads_after_denial == 0
        assert denied_event is not None
        assert denied_event.payload["authorized"] is False
        assert denied_event.payload["reason"] == "identity_not_verified"
        assert denied_event.payload["conversationId"] is None
        assert denied_raw.processing_status == "processed"
