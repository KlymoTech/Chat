"""Actual API/database contracts for the user-supplied Leads export, no provider calls."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.lead_workspace_models import LeadWorkspaceOperations
from northstar_api.models import Role, TenantMembership, User, WorkspaceMembership, WorkspaceRole
from northstar_api.security import create_access_token


@pytest.fixture
async def lead_case(client: AsyncClient, auth_headers: dict[str, str]) -> dict:
    suffix = uuid4().hex[:10]
    created = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": f"Leads review {suffix}", "slug": f"leads-review-{suffix}"},
    )
    assert created.status_code == 201, created.text
    workspace = created.json()
    headers = {**auth_headers, "X-Workspace-ID": workspace["id"]}
    created = await client.post("/api/v1/agents", headers=headers, json={"name": f"Sales {suffix}"})
    assert created.status_code == 201, created.text
    agent = created.json()
    created = await client.post(
        "/api/v1/leads",
        headers=headers,
        json={
            "agentId": agent["id"],
            "name": "Review Prospect",
            "email": f"prospect-{suffix}@example.com",
            "consent": False,
            "fields": {"company": "Example Labs"},
        },
    )
    assert created.status_code == 201, created.text
    return {"headers": headers, "workspace": workspace, "agent": agent, "lead": created.json()}


def endpoint(case: dict, suffix: str) -> str:
    return f"/api/v1/leads/{case['lead']['id']}/{suffix}"


async def candidate(client: AsyncClient, case: dict) -> dict:
    result = await client.get(endpoint(case, "assignment-options"), headers=case["headers"])
    assert result.status_code == 200, result.text
    assert result.json(), "The workspace creator must be assignable"
    return result.json()[0]


async def member(
    case: dict, role: WorkspaceRole = WorkspaceRole.VIEWER, *, all_agents: bool = True
) -> tuple[str, dict]:
    async with SessionFactory() as session:
        user = User(
            name="Review scoped member",
            email=f"{uuid4().hex}@example.com",
            is_active=True,
            password_hash=uuid4().hex,
        )
        session.add(user)
        await session.flush()
        tenant_id, workspace_id = UUID(case["workspace"]["tenantId"]), UUID(case["workspace"]["id"])
        session.add(TenantMembership(tenant_id=tenant_id, user_id=user.id, role=Role.MEMBER))
        session.add(
            WorkspaceMembership(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user.id,
                role=role,
                all_agents_access=all_agents,
            )
        )
        await session.commit()
        token, _ = create_access_token(user.id, tenant_id, Role.MEMBER)
        return str(user.id), {"Authorization": f"Bearer {token}", "X-Workspace-ID": str(workspace_id)}


async def payload(client: AsyncClient, case: dict) -> dict:
    owner = await candidate(client, case)
    return {
        "id": str(uuid4()),
        "version": 0,
        "kind": "call",
        "title": "Product demonstration",
        "dueAt": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        "timezone": "Asia/Kolkata",
        "assigneeKind": owner["kind"],
        "assigneeId": owner["id"],
        "notes": "Review actual requirements",
        "reminderMinutes": 30,
    }


async def test_lead_summary_and_empty_workspace_details(client: AsyncClient, lead_case: dict) -> None:
    case = lead_case
    result = await client.get("/api/v1/leads/summary", headers=case["headers"])
    assert result.status_code == 200, result.text
    assert result.json() == {"total": 1, "new": 1, "qualified": 0, "converted": 0}
    result = await client.get(endpoint(case, "workspace"), headers=case["headers"])
    assert result.status_code == 200, result.text
    assert result.json() == {"lead": case["lead"], "version": 0, "assignment": None, "followUps": []}
    assert case["lead"]["consent"] is False


async def test_assignment_persists_and_rejects_stale_updates(client: AsyncClient, lead_case: dict) -> None:
    case = lead_case
    owner = await candidate(client, case)
    value = {"version": 0, "kind": owner["kind"], "targetId": owner["id"], "note": "Demo requested"}
    saved = await client.put(endpoint(case, "assignment"), headers=case["headers"], json=value)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert saved.json()["assignment"]["id"] == owner["id"]
    assert saved.json()["assignment"]["note"] == "Demo requested"
    reloaded = await client.get(endpoint(case, "workspace"), headers=case["headers"])
    assert reloaded.json() == saved.json()
    stale = await client.put(endpoint(case, "assignment"), headers=case["headers"], json=value)
    assert stale.status_code == 409, stale.text
    async with SessionFactory() as session:
        row = await session.get(LeadWorkspaceOperations, UUID(case["lead"]["id"]))
        assert row is not None and row.version == 1
        assert row.tenant_id == UUID(case["workspace"]["tenantId"])
        assert row.workspace_id == UUID(case["workspace"]["id"])
        event = await session.scalar(
            select(IntegrationAuditEvent).where(
                IntegrationAuditEvent.entity_id == case["lead"]["id"],
                IntegrationAuditEvent.action == "lead.assignment.updated",
            )
        )
        assert event is not None
    # Assignment bookkeeping never changes the externally synchronized custom field payload.
    assert reloaded.json()["lead"]["fields"] == case["lead"]["fields"]


async def test_foreign_assignees_and_restricted_agent_members_are_not_assignable(
    client: AsyncClient, lead_case: dict
) -> None:
    case = lead_case
    restricted_id, _ = await member(case, WorkspaceRole.OPERATOR, all_agents=False)
    choices = await client.get(endpoint(case, "assignment-options"), headers=case["headers"])
    assert all(item["id"] != restricted_id for item in choices.json())
    for target in [str(uuid4()), restricted_id]:
        result = await client.put(
            endpoint(case, "assignment"),
            headers=case["headers"],
            json={"version": 0, "kind": "person", "targetId": target},
        )
        assert result.status_code == 422, result.text
    state = await client.get(endpoint(case, "workspace"), headers=case["headers"])
    assert state.json()["version"] == 0


async def test_viewer_can_read_but_cannot_assign_schedule_or_change_stage(
    client: AsyncClient, lead_case: dict
) -> None:
    case = lead_case
    _, headers = await member(case)
    result = await client.get(endpoint(case, "workspace"), headers=headers)
    assert result.status_code == 200, result.text
    value = await payload(client, case)
    requests = [
        ("PUT", "assignment", {"version": 0, "kind": value["assigneeKind"], "targetId": value["assigneeId"]}),
        ("POST", "follow-ups", value),
        ("PUT", "stage", {"status": "qualified"}),
    ]
    for method, suffix, body in requests:
        result = await client.request(method, endpoint(case, suffix), headers=headers, json=body)
        assert result.status_code == 403, result.text
    assert (await client.get(endpoint(case, "assignment-options"), headers=headers)).status_code == 403


async def test_agent_restriction_applies_to_summary_details_and_manual_creation(
    client: AsyncClient, lead_case: dict
) -> None:
    case = lead_case
    _, headers = await member(case, WorkspaceRole.OPERATOR, all_agents=False)
    assert (await client.get("/api/v1/leads/summary", headers=headers)).json()["total"] == 0
    assert (await client.get(endpoint(case, "workspace"), headers=headers)).status_code == 404
    created = await client.post(
        "/api/v1/leads", headers=headers, json={"agentId": case["agent"]["id"], "name": "Forbidden"}
    )
    assert created.status_code == 404, created.text


async def test_other_workspace_cannot_read_or_mutate_lead(
    client: AsyncClient, auth_headers: dict, lead_case: dict
) -> None:
    case = lead_case
    suffix = uuid4().hex[:10]
    created = await client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": f"Other {suffix}", "slug": f"other-leads-{suffix}"},
    )
    assert created.status_code == 201, created.text
    headers = {**auth_headers, "X-Workspace-ID": created.json()["id"]}
    assert (await client.get("/api/v1/leads/summary", headers=headers)).json()["total"] == 0
    assert (await client.get(endpoint(case, "workspace"), headers=headers)).status_code == 404
    assert (await client.get(endpoint(case, "assignment-options"), headers=headers)).status_code == 404
    result = await client.put(endpoint(case, "stage"), headers=headers, json={"status": "converted"})
    assert result.status_code == 404


async def test_followup_is_durable_idempotent_and_separate_from_outbound_delivery(
    client: AsyncClient, lead_case: dict
) -> None:
    case = lead_case
    value = await payload(client, case)
    saved = await client.post(endpoint(case, "follow-ups"), headers=case["headers"], json=value)
    assert saved.status_code == 201, saved.text
    data = saved.json()
    assert data["version"] == 1 and len(data["followUps"]) == 1
    record = data["followUps"][0]
    assert record["id"] == value["id"] and record["title"] == value["title"]
    assert record["deliveryMode"] == "calendar" and record["status"] == "scheduled"
    assert record["reminderMinutes"] == 30
    repeated = await client.post(endpoint(case, "follow-ups"), headers=case["headers"], json=value)
    assert repeated.status_code == 201 and repeated.json() == data
    changed = await client.post(
        endpoint(case, "follow-ups"), headers=case["headers"], json={**value, "title": "Different"}
    )
    assert changed.status_code == 409, changed.text
    reloaded = await client.get(endpoint(case, "workspace"), headers=case["headers"])
    assert reloaded.json() == data
    result = await client.patch(
        endpoint(case, f"follow-ups/{value['id']}"),
        headers=case["headers"],
        json={"version": 1, "status": "completed"},
    )
    assert result.status_code == 200 and result.json()["followUps"][0]["status"] == "completed"
    assert result.json()["version"] == 2
    assert (
        await client.patch(
            endpoint(case, f"follow-ups/{value['id']}"),
            headers=case["headers"],
            json={"version": 1, "status": "cancelled"},
        )
    ).status_code == 409


@pytest.mark.parametrize(
    "update",
    [
        {"dueAt": "2020-01-01T10:00:00Z"},
        {"dueAt": "2030-01-01T10:00:00"},
        {"timezone": "Invalid/Zone"},
        {"title": "  "},
        {"reminderMinutes": -1},
        {"assigneeId": "nonexistent-user"},
        {"kind": "automatic-email"},
    ],
)
async def test_followup_rejects_invalid_or_unsupported_values(
    client: AsyncClient, lead_case: dict, update: dict
) -> None:
    value = {**await payload(client, lead_case), **update}
    result = await client.post(endpoint(lead_case, "follow-ups"), headers=lead_case["headers"], json=value)
    assert result.status_code == 422, result.text
    assert (await client.get(endpoint(lead_case, "workspace"), headers=lead_case["headers"])).json()[
        "version"
    ] == 0


async def test_status_uses_existing_qualification_and_audit_contract(
    client: AsyncClient, lead_case: dict
) -> None:
    case = lead_case
    result = await client.put(
        endpoint(case, "stage"),
        headers=case["headers"],
        json={"status": "qualified", "note": "Budget confirmed"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "qualified"
    assert (await client.get("/api/v1/leads/summary", headers=case["headers"])).json()["qualified"] == 1
    async with SessionFactory() as session:
        event = await session.scalar(
            select(IntegrationAuditEvent).where(
                IntegrationAuditEvent.entity_id == case["lead"]["id"],
                IntegrationAuditEvent.action == "lead.stage.changed",
            )
        )
        assert event is not None and event.metadata_json["note"] == "Budget confirmed"


async def test_complete_export_respects_agent_and_channel_filters(
    client: AsyncClient, lead_case: dict
) -> None:
    case = lead_case
    params = {"format": "csv", "agent_id": case["agent"]["id"], "channel": "api"}
    result = await client.get("/api/v1/leads/layout/export", headers=case["headers"], params=params)
    assert result.status_code == 200, result.text
    rows = list(csv.reader(io.StringIO(result.content.decode("utf-8-sig"))))
    assert len(rows) == 2 and "Review Prospect" in rows[1]
    for changed in [{"agent_id": str(uuid4())}, {"channel": "whatsapp"}]:
        result = await client.get(
            "/api/v1/leads/layout/export", headers=case["headers"], params={**params, **changed}
        )
        assert result.status_code == 200, result.text
        assert len(list(csv.reader(io.StringIO(result.content.decode("utf-8-sig"))))) == 1
