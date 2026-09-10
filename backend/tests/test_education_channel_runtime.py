from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channel_scope import WorkspaceChannelConnection
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
    seed = uuid.uuid4().hex[:8].upper()
    phone = f"+9198{uuid.uuid4().int % 100_000_000:08d}"

    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={
            "code": f"CHANNEL-AUTH-{seed}",
            "name": f"Channel Authorization Course {seed}",
        },
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"CHANNEL-AUTH-{seed}-A",
            "name": f"Channel Authorization Batch {seed}",
            "startsOn": "2026-01-01",
            "endsOn": "2027-12-31",
        },
    )
    assert batch.status_code == 201, batch.text
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={"studentNumber": f"CHANNEL-{seed}", "name": f"Channel Student {seed}"},
    )
    assert student.status_code == 201, student.text
    identity = await client.post(
        f"/api/v1/education/students/{student.json()['id']}/identities",
        headers=headers,
        json={
            "identityType": "whatsapp",
            "identifier": phone,
            "status": "verified",
        },
    )
    assert identity.status_code == 201, identity.text
    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Channel Runtime Education Agent {seed}",
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
        "phone": phone,
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


async def _scoped_connection(
    session,
    *,
    agent: Agent,
    scope_agent_id: uuid.UUID | None,
) -> ChannelConnection:
    connection = ChannelConnection(
        tenant_id=agent.tenant_id,
        provider=ChannelProvider.WHATSAPP.value,
        name=f"Education runtime {uuid.uuid4().hex}",
        status="healthy",
        configuration_json={"agentId": str(agent.id)},
    )
    session.add(connection)
    await session.flush()
    session.add(
        WorkspaceChannelConnection(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=scope_agent_id,
            connection_id=connection.id,
        )
    )
    await session.flush()
    return connection


async def test_education_channel_runtime_never_enters_lead_path(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, _ = await _seed_authorized_student(client, auth_headers)

    async with SessionFactory() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == uuid.UUID(seeded["agentId"])))
        assert agent is not None
        connection = await _scoped_connection(session, agent=agent, scope_agent_id=agent.id)

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
                phone=seeded["phone"],
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
        education_context = await session.scalar(
            select(EducationConversationContext).where(
                EducationConversationContext.workspace_id == agent.workspace_id,
                EducationConversationContext.agent_id == agent.id,
            )
        )
        authorized_event = await session.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == agent.tenant_id,
                OutboxEvent.event_type == "education.access.authorized.v1",
            )
            .order_by(OutboxEvent.occurred_at.desc())
        )
        assert conversation_count == 1
        assert message_count == 1
        assert lead_count == 0
        assert education_context is not None
        assert str(education_context.student_id) == seeded["studentId"]
        assert str(education_context.enrollment_id) == seeded["enrollmentId"]
        assert str(education_context.course_id) == seeded["courseId"]
        assert str(education_context.batch_id) == seeded["batchId"]
        assert authorized_event is not None
        assert authorized_event.payload["authorized"] is True
        assert authorized_event.payload["studentId"] == seeded["studentId"]
        assert authorized_event.payload["enrollmentId"] == seeded["enrollmentId"]
        assert authorized_event.payload["courseId"] == seeded["courseId"]
        assert authorized_event.payload["batchId"] == seeded["batchId"]
        assert authorized_raw.processing_status == "processed"

        repeated_raw = await _raw_event(
            session,
            tenant_id=agent.tenant_id,
            connection_id=connection.id,
            external_event_id="education-authorized-repeat",
        )
        await _process_education_message(
            session,
            raw=repeated_raw,
            connection=connection,
            canonical=_canonical(
                tenant_id=agent.tenant_id,
                connection_id=connection.id,
                phone=seeded["phone"],
                external_event_id="education-authorized-repeat",
            ),
            agent=agent,
        )
        repeated_conversation_count = int(
            await session.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.workspace_id == agent.workspace_id,
                    Conversation.agent_id == agent.id,
                )
            )
            or 0
        )
        repeated_message_count = int(
            await session.scalar(
                select(func.count(Message.id))
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(Conversation.agent_id == agent.id)
            )
            or 0
        )
        context_count = int(
            await session.scalar(
                select(func.count(EducationConversationContext.id)).where(
                    EducationConversationContext.workspace_id == agent.workspace_id,
                    EducationConversationContext.agent_id == agent.id,
                )
            )
            or 0
        )
        assert repeated_conversation_count == 1
        assert repeated_message_count == 2
        assert context_count == 1
        assert repeated_raw.processing_status == "processed"

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
                phone="+919999999999",
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
        contexts_after_denial = int(
            await session.scalar(
                select(func.count(EducationConversationContext.id)).where(
                    EducationConversationContext.workspace_id == agent.workspace_id,
                    EducationConversationContext.agent_id == agent.id,
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
            .order_by(OutboxEvent.occurred_at.desc())
        )
        assert conversations_after_denial == 1
        assert leads_after_denial == 0
        assert contexts_after_denial == 1
        assert denied_event is not None
        assert denied_event.payload["authorized"] is False
        assert denied_event.payload["reason"] == "identity_not_verified"
        assert denied_event.payload["conversationId"] is None
        assert denied_raw.processing_status == "processed"


async def test_education_channel_runtime_denies_mismatched_connection_agent_scope(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    seeded, headers = await _seed_authorized_student(client, auth_headers)
    other_agent_response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Other Channel Agent {uuid.uuid4().hex[:8]}",
            "description": "Owns the channel scope but not the Education enrollment",
            "purpose": "support",
            "deploymentChannel": "website",
        },
    )
    assert other_agent_response.status_code == 201, other_agent_response.text

    async with SessionFactory() as session:
        education_agent = await session.scalar(
            select(Agent).where(Agent.id == uuid.UUID(seeded["agentId"]))
        )
        other_agent = await session.scalar(
            select(Agent).where(Agent.id == uuid.UUID(other_agent_response.json()["id"]))
        )
        assert education_agent is not None
        assert other_agent is not None
        connection = await _scoped_connection(
            session,
            agent=education_agent,
            scope_agent_id=other_agent.id,
        )
        raw = await _raw_event(
            session,
            tenant_id=education_agent.tenant_id,
            connection_id=connection.id,
            external_event_id="education-scope-denied",
        )

        await _process_education_message(
            session,
            raw=raw,
            connection=connection,
            canonical=_canonical(
                tenant_id=education_agent.tenant_id,
                connection_id=connection.id,
                phone=seeded["phone"],
                external_event_id="education-scope-denied",
            ),
            agent=education_agent,
        )

        conversation_count = int(
            await session.scalar(
                select(func.count(Conversation.id)).where(
                    Conversation.workspace_id == education_agent.workspace_id,
                    Conversation.agent_id == education_agent.id,
                )
            )
            or 0
        )
        lead_count = int(
            await session.scalar(
                select(func.count(Lead.id)).where(
                    Lead.workspace_id == education_agent.workspace_id,
                    Lead.agent_id == education_agent.id,
                )
            )
            or 0
        )
        context_count = int(
            await session.scalar(
                select(func.count(EducationConversationContext.id)).where(
                    EducationConversationContext.workspace_id == education_agent.workspace_id,
                    EducationConversationContext.agent_id == education_agent.id,
                )
            )
            or 0
        )
        denied_event = await session.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.tenant_id == education_agent.tenant_id,
                OutboxEvent.event_type == "education.access.denied.v1",
            )
            .order_by(OutboxEvent.occurred_at.desc())
        )

        assert conversation_count == 0
        assert lead_count == 0
        assert context_count == 0
        assert denied_event is not None
        assert denied_event.payload["authorized"] is False
        assert denied_event.payload["reason"] == "channel_scope_mismatch"
        assert denied_event.payload["conversationId"] is None
        assert raw.processing_status == "processed"
