from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.database import get_session
from northstar_api.dependencies import CurrentPrincipal, WorkspaceWritePrincipal
from northstar_api.lead_crm.domain import LeadLifecycleStatus
from northstar_api.lead_crm.models import LeadActivityEvent, LeadProfile
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.logging import request_id_ctx
from northstar_api.models import Agent, Conversation, Lead
from northstar_api.schemas import LeadCreate, LeadOut, LeadPatch, PageResult
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/leads", tags=["leads"])
DB = Annotated[AsyncSession, Depends(get_session)]
VALID_LEAD_STATUSES = {item.value for item in LeadLifecycleStatus}


def lead_response(lead: Lead) -> LeadOut:
    return LeadOut(
        id=lead.id,
        agent_id=lead.agent_id,
        conversation_id=lead.conversation_id,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
        status=lead.status,
        consent=lead.consent,
        fields=lead.fields_json,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


@router.get("", response_model=PageResult[LeadOut])
async def list_leads(
    principal: CurrentPrincipal,
    session: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None, max_length=320),
    status: str | None = Query(default=None, max_length=40),
    agent_id: UUID | None = Query(default=None),
) -> PageResult[LeadOut]:
    conditions = [Lead.tenant_id == principal.tenant_id]
    if status:
        if status not in VALID_LEAD_STATUSES:
            raise HTTPException(status_code=400, detail="Unsupported lead status")
        conditions.append(Lead.status == status)
    if agent_id:
        conditions.append(Lead.agent_id == agent_id)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                Lead.name.ilike(pattern),
                Lead.email.ilike(pattern),
                Lead.phone.ilike(pattern),
            )
        )
    total = int(await session.scalar(select(func.count()).select_from(Lead).where(*conditions)) or 0)
    leads = (
        await session.scalars(
            select(Lead)
            .where(*conditions)
            .order_by(Lead.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return PageResult(
        items=[lead_response(item) for item in leads], total=total, page=page, page_size=page_size
    )


@router.post("", response_model=LeadOut, status_code=201)
async def create_lead(payload: LeadCreate, principal: WorkspaceWritePrincipal, session: DB) -> LeadOut:
    agent = await session.scalar(
        select(Agent).where(Agent.id == payload.agent_id, Agent.tenant_id == principal.tenant_id)
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    conversation: Conversation | None = None
    if payload.conversation_id:
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == payload.conversation_id,
                Conversation.tenant_id == principal.tenant_id,
                Conversation.agent_id == payload.agent_id,
            )
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    lead = Lead(
        tenant_id=principal.tenant_id,
        agent_id=payload.agent_id,
        conversation_id=payload.conversation_id,
        name=payload.name,
        email=str(payload.email) if payload.email else None,
        phone=payload.phone,
        status=LeadLifecycleStatus.NEW.value,
        consent=payload.consent,
        fields_json=payload.fields,
    )
    session.add(lead)
    await session.flush()
    source_channel = conversation.channel.value if conversation is not None else "api"
    await lead_domain_service.ensure_profile(
        session,
        lead=lead,
        source_channel=source_channel,
        source_provider=source_channel,
        source_external_id=str(conversation.visitor_id) if conversation and conversation.visitor_id else None,
    )
    event_payload = {
        "leadId": str(lead.id),
        "agentId": str(lead.agent_id),
        "conversationId": str(lead.conversation_id) if lead.conversation_id else None,
        "sourceChannel": source_channel,
    }
    # Preserve the existing event for compatibility while introducing the
    # canonical lead-created event for new consumers.
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="lead",
        aggregate_id=lead.id,
        event_type="lead.captured.v1",
        payload=event_payload,
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="lead",
        aggregate_id=lead.id,
        event_type="lead.created.v1",
        payload=event_payload,
    )
    await session.commit()
    return lead_response(lead)


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: UUID,
    payload: LeadPatch,
    principal: WorkspaceWritePrincipal,
    session: DB,
) -> LeadOut:
    if payload.status not in VALID_LEAD_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported lead status")
    lead = await session.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == principal.tenant_id))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    previous = lead.status
    lead.status = payload.status
    profile = await lead_domain_service.ensure_profile(session, lead=lead)
    profile.lifecycle_status = payload.status
    session.add(
        LeadActivityEvent(
            tenant_id=principal.tenant_id,
            lead_id=lead.id,
            event_type="lead.status.changed.v1",
            actor_type="user",
            actor_id=str(principal.user_id),
            correlation_id=request_id_ctx.get(),
            details_json={"previousStatus": previous, "status": payload.status},
        )
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="lead",
        aggregate_id=lead.id,
        event_type="lead.updated.v1",
        payload={"leadId": str(lead.id), "previousStatus": previous, "status": payload.status},
    )
    await session.commit()
    return lead_response(lead)
