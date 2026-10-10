from __future__ import annotations

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
from northstar_api.lead_crm.models import LeadActivityEvent, LeadProfile
from northstar_api.lead_crm.website_lead_scoring import (
    ScorePolicy,
    ScorePolicyUpdate,
    ScorePreview,
    evaluate_score,
)
from northstar_api.models import Lead, Workspace, WorkspaceStatus
from northstar_api.security import Principal
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
    await session.commit()
    return preview.model_copy(update={"current_score": preview.proposed_score})
