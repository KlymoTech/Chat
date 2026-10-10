from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.crm_workflow_schemas import CRMWorkflowOut
from northstar_api.lead_crm.models import LeadActivityEvent, LeadConsent, LeadProfile
from northstar_api.lead_crm.website_internal_automations import (
    InternalAutomation,
    InternalAutomationExecute,
    InternalAutomationRegister,
    InternalAutomationRegisterUpdate,
    operationally_eligible,
)
from northstar_api.lead_crm.website_segments import (
    SegmentRegister,
    SegmentRegisterUpdate,
    WebsiteSegment,
    matches_segment,
)
from northstar_api.lead_crm.website_lead_scoring import (
    ScorePolicy,
    ScorePolicyUpdate,
    ScorePreview,
    evaluate_score,
)
from northstar_api.models import Lead, Workspace, WorkspaceStatus
from northstar_api.security import Principal
from northstar_api.services.notifications import notify_workspace_admins
from northstar_api.services.crm_workflow import crm_workflow_service

router = APIRouter(prefix="/crm", tags=["crm workflow"])
DB = Annotated[AsyncSession, Depends(get_session)]
CRMWorkflowPrincipal = Annotated[
    Principal,
    Depends(require_permissions("crm.view")),
]
CRMManagePrincipal = Annotated[Principal, Depends(require_permissions("crm.manage"))]
LeadScoreWritePrincipal = Annotated[Principal, Depends(require_permissions("leads.update"))]
SCORE_SETTINGS_KEY = "website_lead_scoring"


@router.get("/workflow", response_model=CRMWorkflowOut)
async def get_crm_workflow(
    principal: CRMWorkflowPrincipal,
    session: DB,
    limit: int = Query(default=25, ge=1, le=100),
) -> CRMWorkflowOut:
    """Return the live workspace-scoped Lead-to-CRM workflow and readiness state."""

    assert principal.workspace_id is not None
    return await crm_workflow_service.build(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
        limit=limit,
    )


class ScoreApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_policy_version: int = Field(ge=1)
    expected_score: int = Field(ge=0, le=100)


async def _scoring_workspace(session: AsyncSession, principal: Principal, *, lock: bool = False) -> Workspace:
    if principal.workspace_id is None:
        raise HTTPException(400, "Select a workspace")
    query = select(Workspace).where(
        Workspace.id == principal.workspace_id,
        Workspace.tenant_id == principal.tenant_id,
        Workspace.status == WorkspaceStatus.ACTIVE,
    )
    if lock:
        query = query.with_for_update()
    workspace = await session.scalar(query)
    if workspace is None:
        raise HTTPException(404, "Workspace not found")
    return workspace


def _policy(workspace: Workspace) -> ScorePolicy:
    settings = workspace.settings_json or {}
    stored = settings.get(SCORE_SETTINGS_KEY) if isinstance(settings, dict) else None
    return ScorePolicy.model_validate(stored) if isinstance(stored, dict) else ScorePolicy()


async def _lead_preview(
    session: AsyncSession, principal: Principal, lead_id: UUID, policy: ScorePolicy,
    *, lock: bool = False,
) -> tuple[LeadProfile, ScorePreview]:
    if principal.workspace_id is None:
        raise HTTPException(400, "Select a workspace")
    query = (
        select(Lead, LeadProfile)
        .join(
            LeadProfile,
            (LeadProfile.lead_id == Lead.id) & (LeadProfile.tenant_id == Lead.tenant_id),
        )
        .where(
            Lead.id == lead_id,
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
        )
    )
    if principal.agent_ids is not None:
        query = query.where(Lead.agent_id.in_(principal.agent_ids))
    if lock:
        query = query.with_for_update()
    pair = (await session.execute(query)).first()
    if pair is None:
        raise HTTPException(404, "Lead profile not found in this workspace")
    lead, profile = pair
    preview = evaluate_score(
        policy,
        lead_id=str(lead.id),
        values={
            "source_channel": profile.source_channel,
            "utm_source": profile.utm_source,
            "utm_medium": profile.utm_medium,
            "utm_campaign": profile.utm_campaign,
        },
        current_score=profile.qualification_score,
        qualification_status=profile.qualification_status,
        consent=bool(lead.consent),
        consent_status=profile.consent_status,
        lead_status=lead.status,
    )
    return profile, preview


@router.get("/workflow/scoring-policy", response_model=ScorePolicy)
async def get_lead_scoring_policy(
    principal: CRMWorkflowPrincipal, session: DB,
) -> ScorePolicy:
    workspace = await _scoring_workspace(session, principal)
    return _policy(workspace)


@router.put("/workflow/scoring-policy", response_model=ScorePolicy)
async def save_lead_scoring_policy(
    payload: ScorePolicyUpdate, principal: CRMManagePrincipal, session: DB,
) -> ScorePolicy:
    """Reuse Workspace.settings_json and the integration audit, no parallel lead table."""
    workspace = await _scoring_workspace(session, principal, lock=True)
    before = _policy(workspace)
    if payload.expected_version != before.version:
        raise HTTPException(409, "Scoring policy changed; reload before saving")
    after = ScorePolicy(
        version=before.version + 1, enabled=payload.enabled,
        base_points=payload.base_points, review_threshold=payload.review_threshold,
        rules=payload.rules,
    )
    workspace.settings_json = {
        **dict(workspace.settings_json or {}),
        SCORE_SETTINGS_KEY: after.model_dump(mode="json"),
    }
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="website.scoring.policy.updated",
        entity_type="workspace",
        entity_id=str(workspace.id),
        category="lead",
        before=before.model_dump(mode="json"),
        after=after.model_dump(mode="json"),
    )
    await session.commit()
    return after


@router.get("/workflow/leads/{lead_id}/score-preview", response_model=ScorePreview)
async def preview_lead_score(
    lead_id: UUID, principal: CRMWorkflowPrincipal, session: DB,
) -> ScorePreview:
    workspace = await _scoring_workspace(session, principal)
    _, preview = await _lead_preview(session, principal, lead_id, _policy(workspace))
    return preview


@router.post("/workflow/leads/{lead_id}/apply-score", response_model=ScorePreview)
async def apply_lead_score(
    lead_id: UUID, payload: ScoreApplyRequest,
    principal: LeadScoreWritePrincipal, session: DB,
) -> ScorePreview:
    """Explicit, auditable scoring; does not qualify or contact a customer."""
    workspace = await _scoring_workspace(session, principal, lock=True)
    policy = _policy(workspace)
    if payload.expected_policy_version != policy.version:
        raise HTTPException(409, "Scoring policy changed; refresh your preview")
    profile, preview = await _lead_preview(session, principal, lead_id, policy, lock=True)
    if not preview.eligible or preview.proposed_score is None:
        raise HTTPException(409, preview.ineligible_reason or "Scoring is blocked")
    if profile.qualification_score != payload.expected_score:
        raise HTTPException(409, "Lead score changed; refresh your preview")
    if profile.qualification_score == preview.proposed_score:
        return preview

    matched = [
        item for item in preview.rules if item.matched
    ]
    explanation = "Rule-based score v" + str(policy.version) + ": " + (
        ", ".join(f"{item.field} ({item.points:+d})" for item in matched)
        if matched else "base points only"
    )
    old_score = profile.qualification_score
    profile.qualification_score = preview.proposed_score
    # Qualification reason/status belong to the existing human decision workflow.
    # Scoring explanations are appended to LeadActivityEvent, not overwritten there.
    session.add(LeadActivityEvent(
        tenant_id=principal.tenant_id,
        lead_id=lead_id,
        event_type="website.lead.score_applied",
        actor_type="user",
        actor_id=str(principal.user_id),
        correlation_id=f"score-policy-{policy.version}",
        details_json={
            "policyVersion": policy.version,
            "previousScore": old_score,
            "newScore": preview.proposed_score,
            "recommendation": preview.recommendation,
            "matchedRules": len(matched),
            "explanation": explanation[:1000],
            "qualificationStatusUnchanged": True,
        },
    ))
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="website.lead.score_applied",
        entity_type="lead",
        entity_id=str(lead_id),
        category="lead",
        before={"score": old_score},
        after={"score": preview.proposed_score, "policyVersion": policy.version},
    )
    if old_score < policy.review_threshold <= preview.proposed_score:
        # Reuse existing idempotent *internal* notifications. Never contact the lead.
        await notify_workspace_admins(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace.id,
            title="Lead scoring review requested",
            body="A lead crossed the configured scoring threshold. A human must verify qualification.",
            dedupe_key=f"website-score-review:{lead_id}:{policy.version}",
            category="lead",
            severity="info",
            action_url="/leads",
            action_label="Review lead",
            metadata={"leadId": str(lead_id), "policyVersion": policy.version},
        )
    await session.commit()
    return preview.model_copy(update={"current_score": preview.proposed_score})


SEGMENT_SETTINGS_KEY = "website_lead_segments"
SEGMENT_PREVIEW_LIMIT = 1000


def _segments(workspace: Workspace) -> SegmentRegister:
    stored = (workspace.settings_json or {}).get(SEGMENT_SETTINGS_KEY)
    if not isinstance(stored, dict):
        return SegmentRegister()
    return SegmentRegister.model_validate(stored)


@router.get("/workflow/segments", response_model=SegmentRegister)
async def list_lead_segments(
    principal: CRMWorkflowPrincipal, session: DB,
) -> SegmentRegister:
    """Read only the selected active workspace's versioned segment definitions."""
    return _segments(await _scoring_workspace(session, principal))


@router.put("/workflow/segments", response_model=SegmentRegister)
async def save_lead_segments(
    payload: SegmentRegisterUpdate,
    principal: CRMManagePrincipal, session: DB,
) -> SegmentRegister:
    """Reuse existing workspace settings and audit, with no parallel Lead table."""
    workspace = await _scoring_workspace(session, principal, lock=True)
    previous = _segments(workspace)
    if payload.expected_version != previous.version:
        raise HTTPException(409, "Segments changed; reload before saving")
    updated = SegmentRegister(
        version=previous.version + 1,
        segments=payload.segments,
    )
    workspace.settings_json = {
        **dict(workspace.settings_json or {}),
        SEGMENT_SETTINGS_KEY: updated.model_dump(mode="json"),
    }
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        action="website.segments.updated",
        entity_type="workspace",
        entity_id=str(workspace.id),
        category="lead",
        before={"version": previous.version, "segmentIds": [str(item.id) for item in previous.segments]},
        after={"version": updated.version, "segmentIds": [str(item.id) for item in updated.segments]},
    )
    await session.commit()
    return updated


@router.get("/workflow/segments/{segment_id}/preview")
async def preview_lead_segment(
    segment_id: UUID,
    principal: CRMWorkflowPrincipal, session: DB,
) -> dict[str, object]:
    """Bounded, read-only segment evaluation; no exports or messaging actions."""
    workspace = await _scoring_workspace(session, principal)
    policy = _segments(workspace)
    segment: WebsiteSegment | None = next(
        (item for item in policy.segments if item.id == segment_id), None,
    )
    if segment is None:
        raise HTTPException(404, "Segment not found in this workspace")
    if principal.workspace_id is None:
        raise HTTPException(400, "Select a workspace")

    query = (
        select(Lead, LeadProfile)
        .join(LeadProfile, (
            (LeadProfile.lead_id == Lead.id)
            & (LeadProfile.tenant_id == Lead.tenant_id)
        ))
        .where(
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
        )
        .order_by(Lead.created_at.desc(), Lead.id.desc())
        .limit(SEGMENT_PREVIEW_LIMIT + 1)
    )
    if principal.agent_ids is not None:
        query = query.where(Lead.agent_id.in_(principal.agent_ids))
    entries = (await session.execute(query)).all()
    incomplete = len(entries) > SEGMENT_PREVIEW_LIMIT
    entries = entries[:SEGMENT_PREVIEW_LIMIT]

    latest_marketing_consent: dict[UUID, str] = {}
    if segment.purpose == "marketing" and entries:
        candidate_ids = [lead.id for lead, _ in entries]
        consent_rows = (await session.scalars(
            select(LeadConsent).where(
                LeadConsent.tenant_id == principal.tenant_id,
                LeadConsent.lead_id.in_(candidate_ids),
                LeadConsent.consent_type == "marketing",
            ).order_by(LeadConsent.created_at.desc(), LeadConsent.id.desc())
        )).all()
        for receipt in consent_rows:
            # First row for each lead is the latest signed marketing decision.
            latest_marketing_consent.setdefault(receipt.lead_id, receipt.status)

    matched_count = 0
    missing_count = 0
    blocked_count = 0
    for lead, profile in entries:
        if lead.status in {"archived", "lost", "spam"}:
            blocked_count += 1
            continue
        if (
            not lead.consent
            or str(profile.consent_status or "").strip().lower()
            not in {"granted", "consented", "accepted", "opted_in"}
        ):
            blocked_count += 1
            continue
        if (
            segment.purpose == "marketing"
            and latest_marketing_consent.get(lead.id) != "granted"
        ):
            blocked_count += 1
            continue
        values = {
            "source_channel": profile.source_channel,
            "utm_source": profile.utm_source,
            "utm_medium": profile.utm_medium,
            "utm_campaign": profile.utm_campaign,
            "lifecycle_status": lead.status,
            "qualification_status": profile.qualification_status,
        }
        included, missing = matches_segment(segment, values)
        if missing:
            missing_count += 1
        if included:
            matched_count += 1

    return {
        "segmentId": str(segment.id),
        "policyVersion": policy.version,
        "purpose": segment.purpose,
        "enabled": segment.enabled,
        "matchedLeads": matched_count,
        "blockedByEligibility": blocked_count,
        "unknownInputLeads": missing_count,
        "examinedLeads": len(entries),
        "truncated": incomplete,
        "exactCount": not incomplete,
        "evaluatedAt": datetime.now(UTC).isoformat(),
        "note": (
            "Read-only source-system estimate. No contacts were exported or messaged. "
            "Marketing requires explicit latest marketing consent; processing consent alone is insufficient. "
            "Truncated previews are not complete population totals."
        ),
    }


INTERNAL_AUTOMATION_SETTINGS_KEY = "website_internal_automations"
INTERNAL_AUTOMATION_SCAN_LIMIT = 500


def _internal_automations(workspace: Workspace) -> InternalAutomationRegister:
    stored = (workspace.settings_json or {}).get(INTERNAL_AUTOMATION_SETTINGS_KEY)
    if not isinstance(stored, dict):
        return InternalAutomationRegister()
    return InternalAutomationRegister.model_validate(stored)


def _automation_and_segment(
    workspace: Workspace, automation_id: UUID,
) -> tuple[InternalAutomationRegister, InternalAutomation, WebsiteSegment]:
    register = _internal_automations(workspace)
    automation = next(
        (item for item in register.automations if item.id == automation_id), None,
    )
    if automation is None:
        raise HTTPException(404, "Internal automation not found in this workspace")
    if not automation.enabled:
        raise HTTPException(409, "Internal automation is disabled")
    segment = next(
        (item for item in _segments(workspace).segments if item.id == automation.segment_id),
        None,
    )
    if segment is None or not segment.enabled or segment.purpose != "operations":
        raise HTTPException(409, "Enable an internal operations segment before running this automation")
    return register, automation, segment


async def _internal_automation_candidates(
    session: AsyncSession, principal: Principal, segment: WebsiteSegment,
) -> tuple[list[UUID], int, int, bool, int]:
    """Bounded scan against existing tenant/workspace/agent-scoped CRM leads."""
    if principal.workspace_id is None:
        raise HTTPException(400, "Select a workspace")
    query = (
        select(Lead, LeadProfile)
        .join(LeadProfile, (
            (LeadProfile.lead_id == Lead.id)
            & (LeadProfile.tenant_id == Lead.tenant_id)
        ))
        .where(
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
        )
        .order_by(Lead.created_at.asc(), Lead.id.asc())
        .limit(INTERNAL_AUTOMATION_SCAN_LIMIT + 1)
    )
    if principal.agent_ids is not None:
        query = query.where(Lead.agent_id.in_(principal.agent_ids))
    rows = (await session.execute(query)).all()
    truncated = len(rows) > INTERNAL_AUTOMATION_SCAN_LIMIT
    candidate_ids: list[UUID] = []
    blocked = 0
    missing = 0
    for lead, profile in rows[:INTERNAL_AUTOMATION_SCAN_LIMIT]:
        if not operationally_eligible(
            lead_status=lead.status,
            lead_consent=bool(lead.consent),
            processing_consent=profile.consent_status,
        ):
            blocked += 1
            continue
        included, incomplete = matches_segment(segment, {
            "source_channel": profile.source_channel,
            "utm_source": profile.utm_source,
            "utm_medium": profile.utm_medium,
            "utm_campaign": profile.utm_campaign,
            "lifecycle_status": lead.status,
            "qualification_status": profile.qualification_status,
        })
        if incomplete:
            missing += 1
        if included:
            candidate_ids.append(lead.id)
    return candidate_ids, blocked, missing, truncated, min(
        len(rows), INTERNAL_AUTOMATION_SCAN_LIMIT,
    )


async def _already_notified(
    session: AsyncSession, principal: Principal,
    candidate_ids: list[UUID], correlation: str,
) -> set[UUID]:
    if not candidate_ids:
        return set()
    return set((await session.scalars(select(LeadActivityEvent.lead_id).where(
        LeadActivityEvent.tenant_id == principal.tenant_id,
        LeadActivityEvent.lead_id.in_(candidate_ids),
        LeadActivityEvent.event_type == "website.internal_automation.review_queued",
        LeadActivityEvent.correlation_id == correlation,
    ))).all())


def _automation_correlation(automation: InternalAutomation, version: int) -> str:
    return f"site-automation:{automation.id}:{version}"


@router.get("/workflow/internal-automations", response_model=InternalAutomationRegister)
async def list_internal_automations(
    principal: CRMWorkflowPrincipal, session: DB,
) -> InternalAutomationRegister:
    return _internal_automations(await _scoring_workspace(session, principal))


@router.put("/workflow/internal-automations", response_model=InternalAutomationRegister)
async def save_internal_automations(
    payload: InternalAutomationRegisterUpdate,
    principal: CRMManagePrincipal, session: DB,
) -> InternalAutomationRegister:
    workspace = await _scoring_workspace(session, principal, lock=True)
    previous = _internal_automations(workspace)
    if payload.expected_version != previous.version:
        raise HTTPException(409, "Automations changed; reload before saving")
    segments = {
        item.id: item for item in _segments(workspace).segments
        if item.enabled and item.purpose == "operations"
    }
    for item in payload.automations:
        if item.enabled and item.segment_id not in segments:
            raise HTTPException(422, "Active review automations require an enabled operations segment")
    updated = InternalAutomationRegister(
        version=previous.version + 1, automations=payload.automations,
    )
    workspace.settings_json = {
        **dict(workspace.settings_json or {}),
        INTERNAL_AUTOMATION_SETTINGS_KEY: updated.model_dump(mode="json"),
    }
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace.id,
        actor_user_id=principal.user_id,
        action="website.internal_automations.updated",
        entity_type="workspace",
        entity_id=str(workspace.id),
        category="lead",
        before={"version":previous.version,"automationIds":[str(item.id) for item in previous.automations]},
        after={"version":updated.version,"automationIds":[str(item.id) for item in updated.automations]},
    )
    await session.commit()
    return updated


@router.get("/workflow/internal-automations/{automation_id}/preview")
async def preview_internal_automation(
    automation_id: UUID,
    principal: CRMWorkflowPrincipal, session: DB,
) -> dict[str, object]:
    workspace = await _scoring_workspace(session, principal)
    register, automation, segment = _automation_and_segment(workspace, automation_id)
    candidate_ids, blocked, missing, truncated, examined = (
        await _internal_automation_candidates(session, principal, segment)
    )
    correlation = _automation_correlation(automation, register.version)
    previously_queued = await _already_notified(session, principal, candidate_ids, correlation)
    return {
        "automationId": str(automation.id),
        "policyVersion": register.version,
        "segmentVersion": _segments(workspace).version,
        "eligibleLeads": len(candidate_ids),
        "alreadyQueued": len(previously_queued),
        "remainingEligible": len(candidate_ids) - len(previously_queued),
        "blockedByConsentOrStatus": blocked,
        "unknownInputLeads": missing,
        "examinedLeads": examined,
        "truncated": truncated,
        "maxPerRun": automation.max_per_run,
        "action": "notify_admins",
        "externalDelivery": False,
        "note": (
            "Simulation only. No lead was contacted or changed. "
            "Execute is blocked for truncated scans. "
            "Internal review never authorizes customer marketing."
        ),
    }


@router.post("/workflow/internal-automations/{automation_id}/execute")
async def execute_internal_automation(
    automation_id: UUID,
    payload: InternalAutomationExecute,
    principal: CRMManagePrincipal, session: DB,
) -> dict[str, object]:
    """Explicit idempotent internal-only review actions, serialized by workspace lock."""
    workspace = await _scoring_workspace(session, principal, lock=True)
    register, automation, segment = _automation_and_segment(workspace, automation_id)
    if register.version != payload.expected_policy_version:
        raise HTTPException(409, "Automation policy changed; preview again")
    segment_register = _segments(workspace)
    if segment_register.version != payload.expected_segment_version:
        raise HTTPException(409, "Segment rules changed; preview again")
    candidate_ids, blocked, _, truncated, _ = await _internal_automation_candidates(
        session, principal, segment,
    )
    if truncated:
        raise HTTPException(409, "Lead population exceeds the bounded safety scan; narrow the segment")
    if len(candidate_ids) != payload.expected_eligible_leads:
        raise HTTPException(409, "Eligible Lead count changed; preview again")
    correlation = _automation_correlation(automation, register.version)
    already_queued = await _already_notified(session, principal, candidate_ids, correlation)
    pending = [item for item in candidate_ids if item not in already_queued]
    queued = 0
    no_recipient = 0
    for lead_id in pending[:automation.max_per_run]:
        recipients = await notify_workspace_admins(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace.id,
            title="Internal Lead review requested",
            body="An eligible Lead matched an approved internal operations segment. Review the record manually.",
            dedupe_key=f"internal-review:{automation.id}:{register.version}:{lead_id}",
            category="lead",
            severity="info",
            action_url="/leads",
            action_label="Review Lead",
            metadata={
                "leadId":str(lead_id),
                "automationId":str(automation.id),
                "policyVersion":register.version,
            },
        )
        if recipients == 0:
            no_recipient += 1
            continue
        session.add(LeadActivityEvent(
            tenant_id=principal.tenant_id,
            lead_id=lead_id,
            event_type="website.internal_automation.review_queued",
            actor_type="user",
            actor_id=str(principal.user_id),
            correlation_id=correlation,
            details_json={
                "automationId":str(automation.id),
                "policyVersion":register.version,
                "action":"notify_admins",
                "recipientCount":recipients,
                "externalDelivery":False,
            },
        ))
        queued += 1
    record_audit_event(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace.id,
        actor_user_id=principal.user_id,
        action="website.internal_automation.executed",
        entity_type="workspace",
        entity_id=str(workspace.id),
        category="lead",
        after={
            "automationId":str(automation.id),
            "policyVersion":register.version,
            "eligibleLeads":len(candidate_ids),
            "queuedReviews":queued,
            "blockedByConsentOrStatus":blocked,
            "noRecipients":no_recipient,
            "externalDelivery":False,
        },
    )
    await session.commit()
    return {
        "automationId":str(automation.id),
        "policyVersion":register.version,
        "queuedReviews":queued,
        "previouslyQueued":len(already_queued),
        "noRecipients":no_recipient,
        "remainingEligible":len(pending) - queued,
        "externalDelivery":False,
        "note":"Internal in-app human review only. No Lead was qualified or contacted.",
    }
