"""End-to-end API checks for workspace-scoped, explicitly applied lead scoring."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.audit_models import IntegrationAuditEvent
from northstar_api.lead_crm.models import LeadActivityEvent, LeadConsent, LeadProfile
from northstar_api.notifications import Notification
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
        notifications = (await session.scalars(select(Notification).where(
            Notification.workspace_id == workspace_id,
            Notification.category == "lead",
            Notification.title == "Lead scoring review requested",
        ))).all()
    assert changes == 1
    assert deliveries == 0
    assert len(notifications) == 1
    assert notifications[0].metadata_json["leadId"] == str(lead_id)
    assert notifications[0].action_url == "/leads"


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



async def test_segment_register_preview_requires_separate_marketing_consent(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    headers, lead_id, workspace_id = await _workspace_and_lead(client, auth_headers)
    register_url = "/api/v1/crm/workflow/segments"
    segment_id = uuid.uuid4()
    registration = {
        "expected_version": 0,
        "segments": [{
            "id": str(segment_id),
            "name": "Contact-form leads",
            "enabled": True,
            "purpose": "marketing",
            "logic": "all",
            "include": [{"field": "source_channel", "equals": "widget"}],
            "exclude": [{"field": "utm_source", "equals": "test"}],
        }],
    }
    assert (await client.get(register_url)).status_code == 401
    created = await client.put(register_url, headers=headers, json=registration)
    assert created.status_code == 200, created.text
    assert created.json()["version"] == 1
    assert created.json()["segments"][0]["include"][0]["equals"] == "widget"
    assert (await client.put(register_url, headers=headers, json=registration)).status_code == 409
    url = f"{register_url}/{segment_id}/preview"
    assert (await client.get(url)).status_code == 401

    blocked = await client.get(url, headers=headers)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["matchedLeads"] == 0
    assert blocked.json()["blockedByEligibility"] == 1
    assert blocked.json()["examinedLeads"] == 1
    assert blocked.json()["exactCount"] is True
    assert blocked.json()["truncated"] is False
    assert "contacts" in blocked.json()["note"].lower()
    assert "hanako@example.com" not in blocked.text

    async with SessionFactory() as session:
        session.add(LeadConsent(
            tenant_id=(await session.get(Workspace, workspace_id)).tenant_id,
            lead_id=lead_id, consent_type="marketing",
            status="granted", source="explicit_request",
            channel="email", text_version="marketing-v1",
        ))
        await session.commit()

    allowed = await client.get(url, headers=headers)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["matchedLeads"] == 1
    assert allowed.json()["blockedByEligibility"] == 0

    async with SessionFactory() as session:
        session.add(LeadConsent(
            tenant_id=(await session.get(Workspace, workspace_id)).tenant_id,
            lead_id=lead_id, consent_type="marketing",
            status="withdrawn", source="preference_center",
            channel="email", text_version="marketing-v1",
        ))
        await session.commit()
    revoked = await client.get(url, headers=headers)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["matchedLeads"] == 0
    assert revoked.json()["blockedByEligibility"] == 1
    assert "email" not in revoked.text

    wrong_scope, _, _ = await _workspace_and_lead(client, auth_headers)
    inaccessible = await client.get(url, headers=wrong_scope)
    assert inaccessible.status_code == 404


async def test_segment_registration_rejects_sensitive_fields_and_preserves_settings(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    headers, _, workspace_id = await _workspace_and_lead(client, auth_headers)
    url = "/api/v1/crm/workflow/segments"
    illegal = await client.put(url, headers=headers, json={
        "expected_version": 0,
        "segments": [{
            "id": str(uuid.uuid4()), "name": "Forbidden query",
            "purpose": "operations",
            "include": [{"field": "email", "equals": "someone@example.com"}],
        }],
    })
    assert illegal.status_code == 422
    good = await client.put(url, headers=headers, json={
        "expected_version": 0,
        "segments": [{
            "id": str(uuid.uuid4()), "name": "Internal ops",
            "purpose": "operations",
            "include": [{"field": "source_channel", "equals": "widget"}],
        }],
    })
    assert good.status_code == 200, good.text
    async with SessionFactory() as session:
        workspace = await session.get(Workspace, workspace_id)
        assert workspace is not None
        assert workspace.settings_json["untouched"] == "preserve"
        assert workspace.settings_json["website_lead_segments"]["version"] == 1



async def test_marketing_unsubscribe_preserves_processing_and_is_replay_safe(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    headers, lead_id, workspace_id = await _workspace_and_lead(client, auth_headers)
    async with SessionFactory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        session.add(LeadConsent(
            tenant_id=lead.tenant_id, lead_id=lead.id,
            consent_type="marketing", status="granted",
            source="explicit_double_opt_in", channel="email",
        ))
        await session.commit()
    owner_url = f"/api/v1/site-marketing/leads/{lead_id}"
    public = "/api/v1/site-marketing"

    assert (await client.get(owner_url + "/preferences")).status_code == 401
    first = await client.get(owner_url + "/preferences", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["marketingAllowed"] is True

    signed = await client.post(owner_url + "/unsubscribe-link", headers=headers)
    assert signed.status_code == 200, signed.text
    path = signed.json()["path"]
    assert path.startswith(public + "/unsubscribe/")
    assert "@" not in path
    get_only = await client.get(path)
    assert get_only.status_code == 200, get_only.text
    assert "Unsubscribe from marketing" in get_only.text
    still_active = await client.get(owner_url + "/preferences", headers=headers)
    assert still_active.json()["marketingAllowed"] is True

    changed = await client.post(path)
    assert changed.status_code == 200, changed.text
    assert "You are unsubscribed" in changed.text
    after = await client.get(owner_url + "/preferences", headers=headers)
    assert after.status_code == 200
    assert after.json()["marketingAllowed"] is False
    assert after.json()["marketingStatus"] == "withdrawn"
    assert after.json()["processingConsentPreserved"] is True
    retry = await client.post(path)
    assert retry.status_code == 200, retry.text

    owner_retry = await client.post(owner_url + "/withdraw", headers=headers)
    assert owner_retry.status_code == 200
    assert owner_retry.json()["changed"] is False

    async with SessionFactory() as session:
        lead = await session.get(Lead, lead_id)
        profile = await session.scalar(select(LeadProfile).where(
            LeadProfile.lead_id == lead_id,
        ))
        assert lead is not None and lead.consent is True
        assert profile is not None and profile.consent_status == "granted"
        withdrawn_count = await session.scalar(select(func.count()).select_from(LeadConsent).where(
            LeadConsent.lead_id == lead_id,
            LeadConsent.consent_type == "marketing",
            LeadConsent.status == "withdrawn",
        ))
        message_count = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_type == "lead",
            OutboxEvent.aggregate_id == str(lead_id),
            OutboxEvent.event_type == "lead.marketing.consent.withdrawn.v1",
        ))
        audits = (await session.scalars(select(IntegrationAuditEvent).where(
            IntegrationAuditEvent.entity_type == "lead",
            IntegrationAuditEvent.entity_id == str(lead_id),
            IntegrationAuditEvent.action == "website.marketing.consent.withdrawn",
        ))).all()
    assert withdrawn_count == 1
    assert message_count == 1
    assert len(audits) == 1
    assert audits[0].after_json["marketingConsent"] == "withdrawn"
    assert "email" not in str(audits[0].after_json).lower()
    assert len(path) < 800
    assert str(workspace_id) not in path  # UUIDs are signed inside the opaque payload.


async def test_marketing_unsubscribe_is_workspace_scoped_and_rejects_bad_tokens(
    client: AsyncClient, auth_headers: dict[str, str],
) -> None:
    headers, lead_id, _ = await _workspace_and_lead(client, auth_headers)
    owner_url = f"/api/v1/site-marketing/leads/{lead_id}"
    foreign_headers, _, _ = await _workspace_and_lead(client, auth_headers)
    assert (await client.get(owner_url + "/preferences", headers=foreign_headers)).status_code == 404
    assert (await client.post(owner_url + "/withdraw", headers=foreign_headers)).status_code == 404
    assert (await client.post(owner_url + "/unsubscribe-link", headers=foreign_headers)).status_code == 404
    bad = await client.post("/api/v1/site-marketing/unsubscribe/not-valid")
    assert bad.status_code == 400
    # An owner can register a withdrawal without waiting for outbound marketing.
    withdrawn = await client.post(owner_url + "/withdraw", headers=headers)
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["changed"] is True
    second = await client.post(owner_url + "/withdraw", headers=headers)
    assert second.json()["changed"] is False
