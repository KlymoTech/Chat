"""Run published internal website journeys on the authoritative CRM Lead.

Enrolment is part of the existing first-party form transaction. Due transitions
reuse the existing job dispatcher and notifications; no external marketing
provider, new contact record, or outbound message is created.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.models import LeadActivityEvent, LeadConsent
from northstar_api.models import Lead, Workspace, WorkspaceStatus
from northstar_api.services.notifications import notify_workspace_admins
from northstar_api.services.website_automation_contracts import (
    AutomationGraph, SourceCategory, plan_step,
)
from northstar_api.website_automation_models import (
    WebsiteAutomation, WebsiteAutomationRevision, WebsiteAutomationRun,
)


async def _version(
    session: AsyncSession, automation_id: UUID, version: int,
) -> AutomationGraph | None:
    revision = await session.scalar(select(WebsiteAutomationRevision).where(
        WebsiteAutomationRevision.automation_id == automation_id,
        WebsiteAutomationRevision.version == version,
    ))
    if revision is None:
        return None
    try:
        return AutomationGraph.model_validate(revision.document_json)
    except ValidationError:
        return None


async def enrol_website_lead(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    lead_id: UUID,
    source_category: SourceCategory,
    event_key: str,
) -> int:
    """Insert due runs atomically with Lead/consent/outbox creation.

    Only explicit published workflows can be triggered; the caller's unique
    submission ID is the replay key. CRM dispatch remains unchanged.
    """
    if not event_key or len(event_key) > 130:
        raise ValueError("A bounded durable trigger ID is required")
    automations = (await session.scalars(select(WebsiteAutomation).where(
        WebsiteAutomation.tenant_id == tenant_id,
        WebsiteAutomation.workspace_id == workspace_id,
        WebsiteAutomation.enabled.is_(True),
        WebsiteAutomation.published_version.is_not(None),
    ).order_by(WebsiteAutomation.id).limit(20))).all()
    created = 0
    for automation in automations:
        version = automation.published_version
        if version is None:
            continue
        graph = await _version(session, automation.id, version)
        if graph is None:
            continue
        trigger = graph.first_node()
        requested_event = (
            "lead_accepted" if source_category == "form" else
            "subscription_confirmed"
        )
        if trigger.event != requested_event:
            continue
        exists = await session.scalar(select(WebsiteAutomationRun.id).where(
            WebsiteAutomationRun.automation_id == automation.id,
            WebsiteAutomationRun.trigger_key == event_key,
        ))
        if exists is not None:
            continue
        run = WebsiteAutomationRun(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            automation_id=automation.id,
            lead_id=lead_id,
            trigger_key=event_key,
            published_version=version,
            current_node_id=trigger.id,
            source_category=source_category,
            status="queued",
            due_at=datetime.now(UTC),
            processed_steps=0,
        )
        session.add(run)
        created += 1
    return created


async def _current_consent(
    session: AsyncSession, tenant_id: UUID, lead_id: UUID, kind: str,
) -> bool:
    rows = (await session.scalars(select(LeadConsent).where(
        LeadConsent.tenant_id == tenant_id,
        LeadConsent.lead_id == lead_id,
        LeadConsent.consent_type == kind,
    ).order_by(LeadConsent.created_at.desc(), LeadConsent.id.desc()).limit(1))).all()
    return bool(
        rows and rows[0].status.strip().lower() in {"granted", "accepted", "opted_in"}
        and rows[0].withdrawn_at is None
    )


async def process_due_website_automations(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 25,
) -> int:
    """Bounded, lock-protected transitions; called by the existing dispatcher.

    One node is processed per run per tick, so a malformed or busy workflow
    cannot starve the dispatcher's existing channel/CRM responsibilities.
    """
    now = now or datetime.now(UTC)
    pending = (await session.scalars(select(WebsiteAutomationRun).where(
        WebsiteAutomationRun.status.in_(("queued", "waiting")),
        WebsiteAutomationRun.due_at <= now,
    ).order_by(WebsiteAutomationRun.due_at, WebsiteAutomationRun.id)
     .with_for_update(skip_locked=True).limit(max(1, min(limit, 50))))).all()
    for run in pending:
        run.processed_steps += 1
        if run.processed_steps > 60:
            run.status = "failed"
            run.last_error = "Transition limit exceeded"
            continue
        parent = await session.scalar(select(WebsiteAutomation).where(
            WebsiteAutomation.id == run.automation_id,
            WebsiteAutomation.workspace_id == run.workspace_id,
            WebsiteAutomation.tenant_id == run.tenant_id,
        ))
        workspace = await session.scalar(select(Workspace).where(
            Workspace.id == run.workspace_id,
            Workspace.tenant_id == run.tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        ))
        if (
            parent is None or workspace is None or not parent.enabled
            or parent.published_version != run.published_version
        ):
            run.status = "suppressed"
            run.last_error = "Workflow disabled or superseded"
            continue
        lead = await session.scalar(select(Lead).where(
            Lead.id == run.lead_id, Lead.tenant_id == run.tenant_id,
            Lead.workspace_id == run.workspace_id,
        ))
        if (
            lead is None or lead.status == "archived" or not lead.consent
            or not await _current_consent(session, run.tenant_id, run.lead_id, "processing")
        ):
            run.status = "suppressed"
            run.last_error = "Lead unavailable or processing consent withdrawn"
            continue
        graph = await _version(session, parent.id, run.published_version)
        if graph is None:
            run.status = "failed"
            run.last_error = "Published graph unavailable"
            continue
        try:
            current = graph.by_id(run.current_node_id)
        except StopIteration:
            run.status = "failed"
            run.last_error = "Unknown workflow step"
            continue
        has_marketing_consent = await _current_consent(
            session, run.tenant_id, run.lead_id, "marketing"
        )
        successor, due_at, internal_action, _ = plan_step(
            graph, current.id,
            source_category=(
                "subscription" if run.source_category == "subscription" else "form"
            ),
            marketing_consent=has_marketing_consent,
            at=now,
        )
        if internal_action is not None:
            review = internal_action == "review_lead"
            await notify_workspace_admins(
                session,
                tenant_id=run.tenant_id,
                workspace_id=run.workspace_id,
                title=("Lead requires human review" if review else "Website lead notification"),
                body=("A new website lead is ready for your review." if review else
                      "A first-party lead matched an internal workflow."),
                dedupe_key=f"website-automation:{run.id}:{current.id}",
                category="lead",
                severity="info",
                action_url="/leads",
                action_label="Review leads",
                metadata={
                    "leadId": str(run.lead_id), "automationId": str(parent.id),
                    "automationRunId": str(run.id),
                },
            )
            session.add(LeadActivityEvent(
                tenant_id=run.tenant_id, lead_id=run.lead_id,
                event_type="website.automation." + internal_action,
                actor_type="system", actor_id=None,
                correlation_id=str(run.id),
                details_json={
                    "automationId": str(parent.id), "runId": str(run.id),
                    "version": run.published_version, "nodeId": current.id,
                    "customerContacted": False,
                },
            ))
            record_audit_event(
                session, tenant_id=run.tenant_id, workspace_id=run.workspace_id,
                actor_user_id=None, action="website.automation." + internal_action,
                entity_type="website_automation_run", entity_id=str(run.id),
                category="lead", after={
                    "node": current.id, "version": run.published_version,
                    "customerContacted": False,
                },
            )
        if successor is None:
            run.status = "completed"
        else:
            run.current_node_id = successor
            run.due_at = due_at
            run.status = "waiting" if due_at > now else "queued"
    return len(pending)
