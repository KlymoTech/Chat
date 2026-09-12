from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_student_activity import EducationStudentActivityEvent
from northstar_api.models import Agent, Channel, Conversation, ConversationState, Lead, OutboxEvent


async def _create_education_scope(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    seed: str,
) -> tuple[str, dict[str, str]]:
    agent_response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Upsell Education Agent {seed}",
            "description": "Education upsell routing regression",
            "purpose": "education",
            "deploymentChannel": "website",
        },
    )
    assert agent_response.status_code == 201, agent_response.text
    agent_id = agent_response.json()["id"]

    course = await client.post(
        "/api/v1/education/courses",
        headers=headers,
        json={"code": f"UP-{seed}", "name": f"Upsell Course {seed}"},
    )
    assert course.status_code == 201, course.text
    batch = await client.post(
        "/api/v1/education/batches",
        headers=headers,
        json={
            "courseId": course.json()["id"],
            "code": f"UP-{seed}-B",
            "name": f"Upsell Batch {seed}",
        },
    )
    assert batch.status_code == 201, batch.text
    student = await client.post(
        "/api/v1/education/students",
        headers=headers,
        json={
            "studentNumber": f"UP-{seed}-S",
            "name": f"Upsell Student {seed}",
            "email": f"upsell-{seed.lower()}@example.com",
        },
    )
    assert student.status_code == 201, student.text
    enrollment = await client.post(
        "/api/v1/education/enrollments",
        headers=headers,
        json={
            "studentId": student.json()["id"],
            "courseId": course.json()["id"],
            "batchId": batch.json()["id"],
            "agentId": agent_id,
            "status": "active",
        },
    )
    assert enrollment.status_code == 201, enrollment.text

    activated = await client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text

    return agent_id, {
        "studentId": student.json()["id"],
        "studentName": student.json()["name"],
        "studentEmail": student.json()["email"],
        "courseId": course.json()["id"],
        "batchId": batch.json()["id"],
        "enrollmentId": enrollment.json()["id"],
    }


async def _create_authorized_conversation(
    *,
    workspace_id: str,
    agent_id: str,
    scope: dict[str, str],
    seed: str,
) -> str:
    async with SessionFactory() as session:
        agent = await session.get(Agent, uuid.UUID(agent_id))
        assert agent is not None
        conversation = Conversation(
            tenant_id=agent.tenant_id,
            workspace_id=uuid.UUID(workspace_id),
            agent_id=agent.id,
            visitor_id=f"education-upsell-{seed.lower()}",
            visitor_name=scope["studentName"],
            visitor_email=scope["studentEmail"],
            channel=Channel.WIDGET,
        )
        session.add(conversation)
        await session.flush()
        session.add(
            EducationConversationContext(
                tenant_id=agent.tenant_id,
                workspace_id=uuid.UUID(workspace_id),
                conversation_id=conversation.id,
                agent_id=agent.id,
                student_id=uuid.UUID(scope["studentId"]),
                enrollment_id=uuid.UUID(scope["enrollmentId"]),
                course_id=uuid.UUID(scope["courseId"]),
                batch_id=uuid.UUID(scope["batchId"]),
            )
        )
        conversation_id = str(conversation.id)
        await session.commit()
        return conversation_id


async def test_education_upsell_is_explicit_opt_in_and_idempotent(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    seed = uuid.uuid4().hex[:8].upper()

    settings = await client.get(
        "/api/v1/education/settings/sales-routing",
        headers=headers,
    )
    assert settings.status_code == 200, settings.text
    assert settings.json() == {"createUpsellLeads": False}

    agent_id, scope = await _create_education_scope(client, headers, seed=seed)
    blocked_conversation_id = await _create_authorized_conversation(
        workspace_id=workspace_id,
        agent_id=agent_id,
        scope=scope,
        seed=f"{seed}-BLOCKED",
    )

    blocked = await client.post(
        f"/api/v1/education/conversations/{blocked_conversation_id}/resolve-sales-intent",
        headers=headers,
    )
    assert blocked.status_code == 409, blocked.text
    assert "disabled" in blocked.json()["error"]["message"].lower()

    async with SessionFactory() as session:
        blocked_conversation = await session.get(Conversation, uuid.UUID(blocked_conversation_id))
        assert blocked_conversation is not None
        assert blocked_conversation.state == ConversationState.OPEN
        blocked_leads = list(
            await session.scalars(
                select(Lead).where(Lead.conversation_id == uuid.UUID(blocked_conversation_id))
            )
        )
        assert blocked_leads == []

    enabled = await client.patch(
        "/api/v1/education/settings/sales-routing",
        headers=headers,
        json={"createUpsellLeads": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json() == {"createUpsellLeads": True}

    conversation_id = await _create_authorized_conversation(
        workspace_id=workspace_id,
        agent_id=agent_id,
        scope=scope,
        seed=f"{seed}-NORMAL",
    )

    normal_resolution = await client.post(
        f"/api/v1/conversations/{conversation_id}/resolve",
        headers=headers,
    )
    assert normal_resolution.status_code == 200, normal_resolution.text
    assert normal_resolution.json()["state"] == "resolved"

    async with SessionFactory() as session:
        leads_before_intent = list(
            await session.scalars(select(Lead).where(Lead.conversation_id == uuid.UUID(conversation_id)))
        )
        assert leads_before_intent == []

    first_sales_resolution = await client.post(
        f"/api/v1/education/conversations/{conversation_id}/resolve-sales-intent",
        headers=headers,
    )
    assert first_sales_resolution.status_code == 200, first_sales_resolution.text
    first_payload = first_sales_resolution.json()
    assert first_payload["state"] == "resolved"
    assert first_payload["leadCreated"] is True

    second_sales_resolution = await client.post(
        f"/api/v1/education/conversations/{conversation_id}/resolve-sales-intent",
        headers=headers,
    )
    assert second_sales_resolution.status_code == 200, second_sales_resolution.text
    assert second_sales_resolution.json()["leadCreated"] is False
    assert second_sales_resolution.json()["leadId"] == first_payload["leadId"]

    async with SessionFactory() as session:
        leads = list(
            await session.scalars(select(Lead).where(Lead.conversation_id == uuid.UUID(conversation_id)))
        )
        assert len(leads) == 1
        assert str(leads[0].id) == first_payload["leadId"]
        assert leads[0].fields_json["educationUpsell"] is True
        assert leads[0].fields_json["leadReason"] == "education_upsell"

        activities = list(
            await session.scalars(
                select(EducationStudentActivityEvent).where(
                    EducationStudentActivityEvent.conversation_id == uuid.UUID(conversation_id),
                    EducationStudentActivityEvent.event_type == "conversation.resolved",
                )
            )
        )
        assert len(activities) == 1

        crm_events = list(
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == first_payload["leadId"],
                    OutboxEvent.event_type == "lead.crm.sync.requested.v1",
                )
            )
        )
        assert len(crm_events) == 1


async def test_sales_intent_endpoint_rejects_non_education_agents(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    workspace = await client.get("/api/v1/workspace", headers=auth_headers)
    assert workspace.status_code == 200, workspace.text
    workspace_id = workspace.json()["id"]
    headers = {**auth_headers, "X-Workspace-ID": workspace_id}
    seed = uuid.uuid4().hex[:8]

    agent = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": f"Non Education Upsell {seed}",
            "purpose": "lead_generation",
            "deploymentChannel": "website",
        },
    )
    assert agent.status_code == 201, agent.text

    async with SessionFactory() as session:
        persisted_agent = await session.get(Agent, uuid.UUID(agent.json()["id"]))
        assert persisted_agent is not None
        conversation = Conversation(
            tenant_id=persisted_agent.tenant_id,
            workspace_id=persisted_agent.workspace_id,
            agent_id=persisted_agent.id,
            visitor_id=f"not-education-{seed}",
            visitor_name="Prospect",
            channel=Channel.WIDGET,
        )
        session.add(conversation)
        await session.flush()
        conversation_id = str(conversation.id)
        await session.commit()

    response = await client.post(
        f"/api/v1/education/conversations/{conversation_id}/resolve-sales-intent",
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert "only available for Education agents" in response.json()["error"]["message"]
