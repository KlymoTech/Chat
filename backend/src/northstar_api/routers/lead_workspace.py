"""Additive APIs for the exported Leads designs. Existing CRM routing is unchanged.

Follow-ups are durable workspace records with downloadable calendar reminders.
They do not send email/WhatsApp messages or claim that external CRM activity synced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, Field, field_validator
from sqlalchemy import func, select

from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.domain import LeadLifecycleStatus
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.lead_workspace_models import LeadWorkspaceOperations
from northstar_api.logging import request_id_ctx
from northstar_api.models import Lead, User, WorkspaceMemberAgentAccess, WorkspaceMembership
from northstar_api.modules.workspace.member_state import is_member_suspended
from northstar_api.modules.workspace.store import load_workspace, settings_document
from northstar_api.routers.leads import DB, LeadsUpdatePrincipal, LeadsViewPrincipal, lead_response
from northstar_api.schemas import APIModel, LeadOut
from northstar_api.security import Principal
from northstar_api.services.education_conversation_policy import education_source

router = APIRouter(prefix="/leads", tags=["lead-workspace"])


def lead_scope(principal: Principal) -> list:
    return [
        Lead.tenant_id == principal.tenant_id,
        Lead.workspace_id == principal.workspace_id,
        ~education_source(Lead),
        *((Lead.agent_id.in_(principal.agent_ids),) if principal.agent_ids is not None else ()),
    ]


async def scoped_lead(lead_id: UUID, principal: Principal, session: DB, *, lock: bool = False) -> Lead:
    query = select(Lead).where(Lead.id == lead_id, *lead_scope(principal))
    value = await session.scalar(query.with_for_update() if lock else query)
    if value is None:
        raise HTTPException(404, "Lead not found")
    return value


class LeadSummary(APIModel):
    total: int
    new: int
    qualified: int
    converted: int


@router.get("/summary", response_model=LeadSummary)
async def summary(principal: LeadsViewPrincipal, session: DB) -> LeadSummary:
    rows = (
        await session.execute(
            select(Lead.status, func.count(Lead.id)).where(*lead_scope(principal)).group_by(Lead.status)
        )
    ).all()
    counts = dict(rows)
    return LeadSummary(
        total=sum(counts.values()),
        new=counts.get("new", 0),
        qualified=counts.get("qualified", 0),
        converted=counts.get("converted", 0),
    )


class Assignee(APIModel):
    id: str
    name: str
    kind: Literal["person", "team"]
    role: str = ""


class AssignmentWrite(APIModel):
    version: int = Field(ge=0)
    kind: Literal["person", "team"]
    target_id: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)


class Assignment(Assignee):
    note: str = ""
    assigned_at: str


class FollowUpWrite(APIModel):
    id: UUID
    version: int = Field(ge=0)
    kind: Literal["call", "email", "whatsapp", "meeting", "task"]
    title: str = Field(min_length=1, max_length=160)
    due_at: AwareDatetime
    timezone: str = Field(min_length=1, max_length=80)
    assignee_kind: Literal["person", "team"]
    assignee_id: str = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=2000)
    reminder_minutes: int | None = Field(default=30, ge=0, le=10080)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a follow-up title")
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Choose a valid IANA timezone") from None
        return value


class FollowUp(APIModel):
    id: UUID
    kind: str
    title: str
    due_at: str
    timezone: str
    assignee_kind: str
    assignee_id: str
    assignee_name: str
    notes: str
    reminder_minutes: int | None
    created_at: str
    status: Literal["scheduled", "completed", "cancelled"] = "scheduled"
    delivery_mode: Literal["calendar"] = "calendar"


class LeadWorkspaceOut(APIModel):
    lead: LeadOut
    version: int = 0
    assignment: Assignment | None = None
    follow_ups: list[FollowUp] = Field(default_factory=list)


async def options_for(lead: Lead, principal: Principal, session: DB) -> list[Assignee]:
    _, workspace = await load_workspace(principal, session)
    rows = (
        await session.execute(
            select(User, WorkspaceMembership)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(
                WorkspaceMembership.tenant_id == principal.tenant_id,
                WorkspaceMembership.workspace_id == principal.workspace_id,
                User.is_active.is_(True),
            )
            .order_by(User.name, User.id)
        )
    ).all()
    access = set(
        await session.scalars(
            select(WorkspaceMemberAgentAccess.user_id).where(
                WorkspaceMemberAgentAccess.workspace_id == principal.workspace_id,
                WorkspaceMemberAgentAccess.agent_id == lead.agent_id,
            )
        )
    )
    members = [
        Assignee(id=str(user.id), name=user.name, role=membership.role.value, kind="person")
        for user, membership in rows
        if not is_member_suspended(workspace.settings_json, user.id)
        and (membership.all_agents_access or user.id in access)
    ]
    eligible = {item.id for item in members}
    teams = [
        Assignee(id=team.id, name=team.name, kind="team", role="Workspace team")
        for team in settings_document(workspace).teams.teams
        if (not team.agent_ids or str(lead.agent_id) in team.agent_ids)
        and any(str(member) in eligible for member in team.member_ids)
    ]
    return members + teams


@router.get("/{lead_id}/assignment-options", response_model=list[Assignee])
async def assignment_options(lead_id: UUID, principal: LeadsUpdatePrincipal, session: DB) -> list[Assignee]:
    return await options_for(await scoped_lead(lead_id, principal, session), principal, session)


async def operations(lead: Lead, session: DB) -> LeadWorkspaceOperations | None:
    return await session.scalar(
        select(LeadWorkspaceOperations).where(
            LeadWorkspaceOperations.lead_id == lead.id,
            LeadWorkspaceOperations.tenant_id == lead.tenant_id,
            LeadWorkspaceOperations.workspace_id == lead.workspace_id,
        )
    )


def response(lead: Lead, value: LeadWorkspaceOperations | None) -> LeadWorkspaceOut:
    doc = value.document if value else {}
    return LeadWorkspaceOut(
        lead=lead_response(lead),
        version=value.version if value else 0,
        assignment=doc.get("assignment"),
        follow_ups=doc.get("followUps", []),
    )


async def save(
    lead: Lead,
    current: LeadWorkspaceOperations | None,
    version: int,
    document: dict,
    principal: Principal,
    session: DB,
    event: str,
) -> LeadWorkspaceOut:
    if version != (current.version if current else 0):
        raise HTTPException(409, "This lead changed in another session. Refresh and try again.")
    if current is None:
        current = LeadWorkspaceOperations(
            lead_id=lead.id, tenant_id=lead.tenant_id, workspace_id=lead.workspace_id, version=0, document={}
        )
        session.add(current)
    current.document = document
    current.version += 1
    record_audit_event(
        session,
        tenant_id=lead.tenant_id,
        workspace_id=lead.workspace_id,
        actor_user_id=principal.user_id,
        action=event,
        entity_type="lead",
        entity_id=str(lead.id),
        category="lead",
        metadata={"version": current.version},
    )
    await session.commit()
    return response(lead, current)


@router.get("/{lead_id}/workspace", response_model=LeadWorkspaceOut)
async def detail(lead_id: UUID, principal: LeadsViewPrincipal, session: DB) -> LeadWorkspaceOut:
    lead = await scoped_lead(lead_id, principal, session)
    return response(lead, await operations(lead, session))


@router.put("/{lead_id}/assignment", response_model=LeadWorkspaceOut)
async def assign(
    lead_id: UUID, payload: AssignmentWrite, principal: LeadsUpdatePrincipal, session: DB
) -> LeadWorkspaceOut:
    lead = await scoped_lead(lead_id, principal, session, lock=True)
    target = next(
        (
            item
            for item in await options_for(lead, principal, session)
            if item.id == payload.target_id and item.kind == payload.kind
        ),
        None,
    )
    if target is None:
        raise HTTPException(422, "Choose an active workspace member or team with access to this agent")
    current = await operations(lead, session)
    doc = dict(current.document if current else {})
    doc["assignment"] = Assignment(
        **target.model_dump(), note=payload.note, assigned_at=datetime.now(UTC).isoformat()
    ).model_dump(by_alias=True)
    return await save(lead, current, payload.version, doc, principal, session, "lead.assignment.updated")


@router.post("/{lead_id}/follow-ups", response_model=LeadWorkspaceOut, status_code=201)
async def schedule(
    lead_id: UUID, payload: FollowUpWrite, principal: LeadsUpdatePrincipal, session: DB
) -> LeadWorkspaceOut:
    lead = await scoped_lead(lead_id, principal, session, lock=True)
    current = await operations(lead, session)
    doc = dict(current.document if current else {})
    records = list(doc.get("followUps", []))
    existing = next((item for item in records if item["id"] == str(payload.id)), None)
    normalized = payload.model_dump(by_alias=True, mode="json", exclude={"version"})
    normalized["dueAt"] = payload.due_at.astimezone(UTC).isoformat()
    if existing:
        if any(existing.get(key) != value for key, value in normalized.items()):
            raise HTTPException(409, "Follow-up request ID was already used with different data")
        return response(lead, current)
    if payload.due_at <= datetime.now(UTC):
        raise HTTPException(422, "Choose a future follow-up time")
    if len(records) >= 100:
        raise HTTPException(409, "This lead has reached the limit of 100 follow-up records")
    target = next(
        (
            item
            for item in await options_for(lead, principal, session)
            if item.id == payload.assignee_id and item.kind == payload.assignee_kind
        ),
        None,
    )
    if target is None:
        raise HTTPException(422, "Choose an active workspace assignee with access to this agent")
    records.append(
        {
            **normalized,
            "assigneeName": target.name,
            "createdAt": datetime.now(UTC).isoformat(),
            "status": "scheduled",
            "deliveryMode": "calendar",
        }
    )
    doc["followUps"] = records
    return await save(lead, current, payload.version, doc, principal, session, "lead.follow_up.scheduled")


class FollowUpStateWrite(APIModel):
    version: int = Field(ge=0)
    status: Literal["completed", "cancelled"]


@router.patch("/{lead_id}/follow-ups/{follow_up_id}", response_model=LeadWorkspaceOut)
async def follow_up_state(
    lead_id: UUID,
    follow_up_id: UUID,
    payload: FollowUpStateWrite,
    principal: LeadsUpdatePrincipal,
    session: DB,
) -> LeadWorkspaceOut:
    lead = await scoped_lead(lead_id, principal, session, lock=True)
    current = await operations(lead, session)
    doc = dict(current.document if current else {})
    records = [dict(item) for item in doc.get("followUps", [])]
    record = next((item for item in records if item["id"] == str(follow_up_id)), None)
    if record is None:
        raise HTTPException(404, "Follow-up not found")
    record["status"] = payload.status
    doc["followUps"] = records
    return await save(lead, current, payload.version, doc, principal, session, "lead.follow_up.updated")


class LeadStageWrite(APIModel):
    status: LeadLifecycleStatus
    note: str = Field(default="", max_length=2000)


@router.put("/{lead_id}/stage", response_model=LeadOut)
async def stage(
    lead_id: UUID, payload: LeadStageWrite, principal: LeadsUpdatePrincipal, session: DB
) -> LeadOut:
    lead = await scoped_lead(lead_id, principal, session, lock=True)
    await lead_domain_service.update_status(
        session,
        lead=lead,
        status=payload.status,
        actor_id=str(principal.user_id),
        correlation_id=request_id_ctx.get(),
    )
    record_audit_event(
        session,
        tenant_id=lead.tenant_id,
        workspace_id=lead.workspace_id,
        actor_user_id=principal.user_id,
        action="lead.stage.changed",
        entity_type="lead",
        entity_id=str(lead.id),
        category="lead",
        metadata={"note": payload.note, "status": payload.status.value},
    )
    await session.commit()
    await session.refresh(lead)
    return lead_response(lead)
