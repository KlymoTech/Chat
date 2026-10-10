"""Existing CRM automation APIs: consent-gated simulation and idempotent admin review."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.models import LeadActivityEvent, LeadProfile
from northstar_api.models import (
    Lead, OutboxEvent, TenantMembership, User, Workspace, WorkspaceMembership,
    WorkspaceRole,
)
from northstar_api.notifications import Notification

pytestmark = pytest.mark.usefixtures("crm_test_plan")


async def _seed_review_workspace(
    client: AsyncClient, headers: dict[str, str],
) -> tuple[dict[str, str], UUID, UUID, UUID]:
    suffix = uuid4().hex[:10]
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.email == "owner@example.com"))
        assert user is not None
        member = await session.scalar(select(TenantMembership).where(
            TenantMembership.user_id == user.id,
        ))
        assert member is not None
        workspace = Workspace(
            tenant_id=member.tenant_id, name="Automation " + suffix,
            slug="automation-" + suffix, created_by=user.id,
            settings_json={"existing_setting": "preserved"},
        )
        session.add(workspace)
        await session.flush()
        session.add(WorkspaceMembership(
            tenant_id=member.tenant_id,
            workspace_id=workspace.id, user_id=user.id,
            role=WorkspaceRole.ADMIN, all_agents_access=True,
        ))
        await session.commit()
        scope = workspace.id
        tenant_id = member.tenant_id

    authorized = {**headers, "X-Workspace-ID": str(scope)}
    created = await client.post("/api/v1/agents", headers=authorized, json={
        "name": "Automation agent " + suffix,
        "description": "Existing lead review integration",
        "purpose": "lead_generation",
        "deploymentChannel": "website",
    })
    assert created.status_code == 201, created.text
    agent_id = UUID(created.json()["id"])
    eligible = uuid4()
    blocked = uuid4()
    async with SessionFactory() as session:
        for lead_id, consent, status in ((eligible, True, "granted"), (blocked, False, "withdrawn")):
            session.add(Lead(
                id=lead_id, tenant_id=tenant_id,
                workspace_id=scope, agent_id=agent_id,
                status="new", consent=consent,
                name="Existing CRM lead", fields_json={},
            ))
            await session.flush()
            session.add(LeadProfile(
                tenant_id=tenant_id, lead_id=lead_id,
                source_channel="website_form", consent_status=status,
                qualification_status="pending",
            ))
        await session.commit()
    return authorized, eligible, blocked, scope


async def test_internal_review_preview_execute_and_idempotent_replay(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    headers, eligible, blocked, scope = await _seed_review_workspace(client, auth_headers)
    segment_id = str(uuid4())
    automation_id = str(uuid4())
    segment_path = "/api/v1/crm/workflow/segments"
    automations_path = "/api/v1/crm/workflow/internal-automations"

    assert (await client.get(automations_path)).status_code == 401
    original = await client.get(automations_path, headers=headers)
    assert original.status_code == 200, original.text
    assert original.json() == {"version": 0, "automations": []}

    configured_segment = await client.put(segment_path, headers=headers, json={
        "expected_version": 0,
        "segments": [{
            "id": segment_id, "name": "First-party enquiries",
            "purpose": "operations", "enabled": True,
            "logic": "all",
            "include": [{"field": "source_channel", "equals": "website_form"}],
            "exclude": [],
        }],
    })
    assert configured_segment.status_code == 200, configured_segment.text
    assert configured_segment.json()["version"] == 1

    rules = [{
        "id": automation_id,
        "name": "Review leads from first-party forms",
        "segment_id": segment_id,
        "enabled": True, "action": "notify_admins",
        "max_per_run": 5,
    }]
    saved = await client.put(automations_path, headers=headers, json={
        "expected_version": 0, "automations": rules,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert (await client.put(automations_path, headers=headers, json={
        "expected_version": 0, "automations": rules,
    })).status_code == 409

    preview_link = automations_path + "/" + automation_id + "/preview"
    execute_link = automations_path + "/" + automation_id + "/execute"
    preview = await client.get(preview_link, headers=headers)
    assert preview.status_code == 200, preview.text
    info = preview.json()
    assert info["externalDelivery"] is False
    assert info["eligibleLeads"] == 1
    assert info["blockedByConsentOrStatus"] == 1
    assert info["remainingEligible"] == 1
    assert info["truncated"] is False

    async with SessionFactory() as session:
        before_activities = await session.scalar(select(func.count()).select_from(LeadActivityEvent).where(
            LeadActivityEvent.lead_id == eligible,
            LeadActivityEvent.event_type == "website.internal_automation.review_queued",
        ))
    assert before_activities == 0  # Preview must be read-only.

    payload = {
        "expected_policy_version": info["policyVersion"],
        "expected_segment_version": info["segmentVersion"],
        "expected_eligible_leads": info["eligibleLeads"],
    }
    assert (await client.post(execute_link, json=payload)).status_code == 401
    executed = await client.post(execute_link, headers=headers, json=payload)
    assert executed.status_code == 200, executed.text
    assert executed.json()["queuedReviews"] == 1
    assert executed.json()["externalDelivery"] is False

    repeated = await client.post(execute_link, headers=headers, json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["queuedReviews"] == 0
    assert repeated.json()["previouslyQueued"] == 1

    after_preview = await client.get(preview_link, headers=headers)
    assert after_preview.json()["remainingEligible"] == 0

    async with SessionFactory() as session:
        activities = (await session.scalars(select(LeadActivityEvent).where(
            LeadActivityEvent.lead_id == eligible,
            LeadActivityEvent.event_type == "website.internal_automation.review_queued",
        ))).all()
        blocked_activity = await session.scalar(select(func.count()).select_from(LeadActivityEvent).where(
            LeadActivityEvent.lead_id == blocked,
            LeadActivityEvent.event_type == "website.internal_automation.review_queued",
        ))
        notifications = (await session.scalars(select(Notification).where(
            Notification.workspace_id == scope,
            Notification.title == "Internal Lead review requested",
        ))).all()
        external_delivery_events = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_type == "lead",
            OutboxEvent.aggregate_id == str(eligible),
            OutboxEvent.event_type == "lead.crm.sync.requested.v1",
        ))
        workspace = await session.get(Workspace, scope)
    assert len(activities) == 1
    assert activities[0].details_json["externalDelivery"] is False
    assert blocked_activity == 0
    assert len(notifications) == 1
    assert notifications[0].metadata_json["leadId"] == str(eligible)
    assert external_delivery_events == 0
    assert workspace is not None and workspace.settings_json["existing_setting"] == "preserved"


async def test_internal_automation_requires_active_operational_segment_and_fresh_versions(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    headers, _, _, _ = await _seed_review_workspace(client, auth_headers)
    automation_id = str(uuid4())
    marketing_segment_id = str(uuid4())
    segment = await client.put("/api/v1/crm/workflow/segments", headers=headers, json={
        "expected_version": 0,
        "segments": [{
            "id": marketing_segment_id, "name": "Marketing leads",
            "purpose": "marketing", "enabled": True, "logic": "all",
            "include": [{"field": "source_channel", "equals": "website_form"}],
            "exclude": [],
        }],
    })
    assert segment.status_code == 200, segment.text
    path = "/api/v1/crm/workflow/internal-automations"
    unsafe = await client.put(path, headers=headers, json={
        "expected_version": 0,
        "automations": [{
            "id": automation_id, "name": "Never run marketing from internal review",
            "segment_id": marketing_segment_id, "enabled": True,
            "action": "notify_admins", "max_per_run": 5,
        }],
    })
    assert unsafe.status_code == 422, unsafe.text

    # Disabled definitions can be saved without executing; preview still fails closed.
    draft = await client.put(path, headers=headers, json={
        "expected_version": 0,
        "automations": [{
            "id": automation_id, "name": "Disabled placeholder",
            "segment_id": marketing_segment_id, "enabled": False,
            "action": "notify_admins", "max_per_run": 5,
        }],
    })
    assert draft.status_code == 200, draft.text
    preview = await client.get(path + "/" + automation_id + "/preview", headers=headers)
    assert preview.status_code == 409
    assert (await client.get(path + "/" + str(uuid4()) + "/preview", headers=headers)).status_code == 404
