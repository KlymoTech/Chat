"""End-to-end API checks for workspace-scoped, explicitly applied lead scoring."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.models import LeadActivityEvent, LeadProfile
from northstar_api.models import (
    Lead, OutboxEvent, TenantMembership, User, Workspace, WorkspaceMembership,
    WorkspaceRole,
)

pytestmark = pytest.mark.usefixtures("crm_test_plan")


async def _workspace_and_lead(
    client: AsyncClient, headers: dict[str, str], *, consent: bool = True,
) -> tuple[dict[str, str], uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex[:10]
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == "owner@example.com"))
        assert user is not None
        tenant = await session.scalar(
            select(TenantMembership).where(TenantMembership.user_id == user.id)
        )
        assert tenant is not None
        workspace = Workspace(
            tenant_id=tenant.tenant_id, name="Scoring " + suffix,
            slug="score-" + suffix, settings_json={"untouched": "preserve"},
            created_by=user.id,
        )
        session.add(workspace)
        await session.flush()
        session.add(WorkspaceMembership(
            tenant_id=tenant.tenant_id, workspace_id=workspace.id,
            user_id=user.id, role=WorkspaceRole.ADMIN, all_agents_access=True,
        ))
        await session.commit()
        scope = workspace.id

    authorized = {**headers, "X-Workspace-ID": str(scope)}
    agent = await client.post("/api/v1/agents", headers=authorized, json={
        "name": "Scoring agent " + suffix, "description": "Score API integration",
        "purpose": "lead_generation", "deploymentChannel": "website",
    })
    assert agent.status_code == 201, agent.text
    async with SessionFactory() as session:
        lead = Lead(
            tenant_id=tenant.tenant_id, workspace_id=scope,
            agent_id=uuid.UUID(agent.json()["id"]),
            status="new", consent=consent, name="Test lead",
            fields_json={},
        )
        session.add(lead)
        await session.flush()
        session.add(LeadProfile(
            tenant_id=tenant.tenant_id, lead_id=lead.id,
            source_channel="widget", utm_source="google",
            consent_status="granted" if consent else "withdrawn",
            qualification_score=0, qualification_status="pending",
            qualification_reason="Existing manual assessment — preserve",
        ))
        await session.commit()
        return authorized, lead.id, scope


async def test_scoring_policy_preview_apply_audit_and_idempotent_noop(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    headers, lead_id, workspace_id = await _workspace_and_lead(client, auth_headers)
    base = "/api/v1/crm/workflow/scoring-policy"
    preview_url = f"/api/v1/crm/workflow/leads/{lead_id}/score-preview"
    apply_url = f"/api/v1/crm/workflow/leads/{lead_id}/apply-score"

    assert (await client.get(base)).status_code == 401
    original = await client.get(base, headers=headers)
    assert original.status_code == 200, original.text
    assert original.json()["version"] == 0
    assert original.json()["enabled"] is False

    new_policy = {
        "expected_version": 0, "enabled": True, "base_points": 15,
        "review_threshold": 45,
        "rules": [
            {"field": "source_channel", "equals": "Widget", "points": 20},
            {"field": "utm_source", "equals": "GOOGLE", "points": 15},
        ],
    }
    assert (await client.put(base, json=new_policy)).status_code == 401
    saved = await client.put(base, headers=headers, json=new_policy)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert saved.json()["rules"][0]["equals"] == "widget"
    assert (await client.put(base, headers=headers, json=new_policy)).status_code == 409

    preview = await client.get(preview_url, headers=headers)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result["eligible"] is True
    assert result["proposed_score"] == 50
    assert result["current_score"] == 0
    assert result["recommendation"] == "review"
    assert result["qualification_status"] == "pending"

    assert (await client.post(apply_url, json={
        "expected_policy_version": 1, "expected_score": 0,
    })).status_code == 401
    applied = await client.post(apply_url, headers=headers, json={
        "expected_policy_version": 1, "expected_score": 0,
    })
    assert applied.status_code == 200, applied.text
    assert applied.json()["current_score"] == 50

    stale = await client.post(apply_url, headers=headers, json={
        "expected_policy_version": 1, "expected_score": 0,
    })
    assert stale.status_code == 409
    repeat = await client.post(apply_url, headers=headers, json={
        "expected_policy_version": 1, "expected_score": 50,
    })
    assert repeat.status_code == 200, repeat.text

    async with SessionFactory() as session:
        profile = await session.scalar(select(LeadProfile).where(LeadProfile.lead_id == lead_id))
        assert profile is not None
        assert profile.qualification_score == 50
        assert profile.qualification_status == "pending"  # Score does not qualify the lead.
        assert profile.qualification_reason == "Existing manual assessment — preserve"
        stored_workspace = await session.get(Workspace, workspace_id)
        assert stored_workspace is not None
        assert stored_workspace.settings_json["untouched"] == "preserve"
        changes = await session.scalar(select(func.count()).select_from(LeadActivityEvent).where(
            LeadActivityEvent.lead_id == lead_id,
            LeadActivityEvent.event_type == "website.lead.score_applied",
        ))
        event = await session.scalar(select(LeadActivityEvent).where(
            LeadActivityEvent.lead_id == lead_id,
            LeadActivityEvent.event_type == "website.lead.score_applied",
        ))
        assert event is not None
        assert "source_channel" in event.details_json["explanation"]
        deliveries = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_type == "lead", OutboxEvent.aggregate_id == str(lead_id),
            OutboxEvent.event_type == "lead.crm.sync.requested.v1",
        ))
    assert changes == 1
    assert deliveries == 0


async def test_scoring_blocks_withdrawn_consent_and_foreign_workspace_leads(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    headers, lead_id, _ = await _workspace_and_lead(client, auth_headers, consent=False)
    base = "/api/v1/crm/workflow/scoring-policy"
    updated = await client.put(base, headers=headers, json={
        "expected_version": 0, "enabled": True, "base_points": 30,
        "review_threshold": 50, "rules": [],
    })
    assert updated.status_code == 200, updated.text
    link = f"/api/v1/crm/workflow/leads/{lead_id}/score-preview"
    preview = await client.get(link, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["eligible"] is False
    assert preview.json()["proposed_score"] is None
    rejected = await client.post(
        f"/api/v1/crm/workflow/leads/{lead_id}/apply-score",
        headers=headers, json={"expected_policy_version": 1, "expected_score": 0},
    )
    assert rejected.status_code == 409

    other_headers, _, _ = await _workspace_and_lead(client, auth_headers)
    foreign = await client.get(link, headers=other_headers)
    assert foreign.status_code == 404


async def test_scoring_rejects_sensitive_fields_and_rule_duplicates(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    headers, _, _ = await _workspace_and_lead(client, auth_headers)
    path = "/api/v1/crm/workflow/scoring-policy"
    for rules in (
        [{"field": "email", "equals": "someone@example.com", "points": 10}],
        [
            {"field": "utm_source", "equals": "google", "points": 10},
            {"field": "utm_source", "equals": "GOOGLE", "points": 20},
        ],
    ):
        result = await client.put(path, headers=headers, json={
            "expected_version": 0, "enabled": True,
            "base_points": 0, "review_threshold": 50, "rules": rules,
        })
        assert result.status_code == 422, result.text
