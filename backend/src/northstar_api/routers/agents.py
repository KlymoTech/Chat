from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose, set_agent_purpose
from northstar_api.config import get_settings
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.lead_crm.channel_scope import AgentChannelBinding
from northstar_api.models import (
    Agent,
    AgentStatus,
    Conversation,
    ConversationState,
    KnowledgeSource,
    default_appearance,
)
from northstar_api.schemas import (
    AgentAppearance,
    AgentCreate,
    AgentDuplicate,
    AgentModelProfile,
    AgentOut,
    AgentPatch,
    AgentSecurity,
    APIModel,
)
from northstar_api.security import Principal
from northstar_api.services.localization import localized_appearance
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/agents", tags=["agents"])
DB = Annotated[AsyncSession, Depends(get_session)]
AgentsViewPrincipal = Annotated[Principal, Depends(require_permissions("agents.view"))]
AgentsCreatePrincipal = Annotated[Principal, Depends(require_permissions("agents.create"))]
AgentsUpdatePrincipal = Annotated[Principal, Depends(require_permissions("agents.update"))]
AgentsDeletePrincipal = Annotated[Principal, Depends(require_permissions("agents.delete"))]

AgentChannelType = Literal[
    "website",
    "whatsapp",
    "telegram",
    "instagram",
    "facebook",
    "slack",
    "teams",
    "api",
    "notion",
    "zapier",
]
LEGACY_APPEARANCE_CHANNELS = {
    "website",
    "whatsapp",
    "instagram",
    "facebook",
    "slack",
    "teams",
    "api",
    "notion",
    "zapier",
}

GENERIC_SUPPORT_INSTRUCTIONS = (
    "Help visitors with accurate, concise answers. Use trusted knowledge first and clearly say when information is unavailable."
)
PURPOSE_STARTER_INSTRUCTIONS: dict[AgentPurpose, str] = {
    AgentPurpose.SUPPORT: (
        "Answer customer questions using trusted knowledge. Be clear, helpful, and escalate when information is missing."
    ),
    AgentPurpose.LEAD_GENERATION: (
        "Qualify each lead with one useful question at a time, understand their needs, and recommend the appropriate next step."
    ),
    AgentPurpose.EDUCATION: (
        "Support enrolled students using only authorized course knowledge. Do not expose private course content until "
        "the platform has verified the student's active enrollment. Escalate identity or enrollment problems instead of guessing."
    ),
}


class AgentCreateWithChannel(AgentCreate):
    deployment_channel: AgentChannelType = "website"
    purpose: AgentPurpose | None = None


class AgentDuplicateWithChannel(AgentDuplicate):
    deployment_channel: AgentChannelType = "website"


class AgentPatchWithPurpose(AgentPatch):
    purpose: AgentPurpose | None = None


class AgentOutWithPurpose(AgentOut):
    purpose: AgentPurpose


class AgentChannelPatch(APIModel):
    channel_type: AgentChannelType


class AgentChannelOut(APIModel):
    agent_id: UUID
    workspace_id: UUID
    channel_type: AgentChannelType


def _create_purpose(payload: AgentCreateWithChannel) -> AgentPurpose:
    if payload.purpose is not None:
        return payload.purpose
    # Preserve the old template contract for API clients that predate purpose.
    if payload.template == "lead":
        return AgentPurpose.LEAD_GENERATION
    return AgentPurpose.SUPPORT


def _starter_instructions(payload: AgentCreateWithChannel, purpose: AgentPurpose) -> str:
    # Before Agent Purpose existed, an omitted/blank template created a generic
    # support Agent while template="support" selected the specialized support
    # starter. Keep both behaviors so this schema extension is non-breaking.
    if purpose == AgentPurpose.SUPPORT and payload.template != "support":
        return GENERIC_SUPPORT_INSTRUCTIONS
    return PURPOSE_STARTER_INSTRUCTIONS[purpose]


async def _channel_binding(session: AsyncSession, agent: Agent) -> AgentChannelBinding:
    value = await session.scalar(
        select(AgentChannelBinding).where(
            AgentChannelBinding.tenant_id == agent.tenant_id,
            AgentChannelBinding.workspace_id == agent.workspace_id,
            AgentChannelBinding.agent_id == agent.id,
        )
    )
    if value is None:
        raw = str((agent.appearance or {}).get("deploymentChannel") or "website").lower()
        supported = {
            "website",
            "whatsapp",
            "telegram",
            "instagram",
            "facebook",
            "slack",
            "teams",
            "api",
            "notion",
            "zapier",
        }
        value = AgentChannelBinding(
            tenant_id=agent.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            channel_type=raw if raw in supported else "website",
        )
        session.add(value)
        await session.flush()
    return value


async def agent_response(session: AsyncSession, agent: Agent) -> AgentOutWithPurpose:
    conversations = int(
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.tenant_id == agent.tenant_id, Conversation.agent_id == agent.id)
        )
        or 0
    )
    resolved = int(
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.tenant_id == agent.tenant_id,
                Conversation.agent_id == agent.id,
                Conversation.state == ConversationState.RESOLVED,
            )
        )
        or 0
    )
    knowledge = int(
        await session.scalar(
            select(func.count())
            .select_from(KnowledgeSource)
            .where(KnowledgeSource.tenant_id == agent.tenant_id, KnowledgeSource.agent_id == agent.id)
        )
        or 0
    )
    purpose = await get_agent_purpose(
        session,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
    )
    return AgentOutWithPurpose(
        id=agent.id,
        workspace_id=agent.workspace_id,
        public_id=agent.public_id,
        name=agent.name,
        description=agent.description,
        instructions=agent.instructions,
        status=agent.status,
        tone=agent.tone,
        language=agent.language,
        avatar=agent.avatar,
        purpose=purpose,
        conversations=conversations,
        resolution_rate=round((resolved / conversations) * 100, 1) if conversations else 0,
        knowledge_count=knowledge,
        last_updated=agent.updated_at,
        created_at=agent.created_at,
        appearance=AgentAppearance.model_validate(agent.appearance),
        model=AgentModelProfile.model_validate(agent.model_profile),
        security=AgentSecurity.model_validate(agent.security),
    )


async def scoped_agent(
    session: AsyncSession,
    tenant_id: UUID,
    agent_id: UUID,
    *,
    workspace_id: UUID | None = None,
    allowed_agent_ids: frozenset[UUID] | None = None,
) -> Agent:
    conditions = [Agent.id == agent_id, Agent.tenant_id == tenant_id, Agent.deleted_at.is_(None)]
    if workspace_id:
        conditions.append(Agent.workspace_id == workspace_id)
    if allowed_agent_ids is not None:
        conditions.append(Agent.id.in_(allowed_agent_ids))
    agent = await session.scalar(select(Agent).where(*conditions))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("", response_model=list[AgentOutWithPurpose])
async def list_agents(principal: AgentsViewPrincipal, session: DB) -> list[AgentOutWithPurpose]:
    conditions = [
        Agent.tenant_id == principal.tenant_id,
        Agent.workspace_id == principal.workspace_id,
        Agent.deleted_at.is_(None),
    ]
    if principal.agent_ids is not None:
        conditions.append(Agent.id.in_(principal.agent_ids))
    agents = (
        await session.scalars(select(Agent).where(*conditions).order_by(Agent.updated_at.desc()))
    ).all()
    return [await agent_response(session, agent) for agent in agents]


@router.post("", response_model=AgentOutWithPurpose, status_code=201)
async def create_agent(
    payload: AgentCreateWithChannel,
    principal: AgentsCreatePrincipal,
    session: DB,
) -> AgentOutWithPurpose:
    purpose = _create_purpose(payload)
    appearance = default_appearance()
    appearance.update(localized_appearance(payload.language))
    # Keep the legacy appearance field for old clients. Telegram is represented
    # only by the relational binding until the legacy AgentAppearance schema is retired.
    appearance["deploymentChannel"] = (
        payload.deployment_channel
        if payload.deployment_channel in LEGACY_APPEARANCE_CHANNELS
        else "website"
    )
    instructions = _starter_instructions(payload, purpose)
    # Education Agents cannot be made live before the enrollment authorization
    # layer exists. Creating them in draft prevents private knowledge from being
    # exposed through the existing generic runtime while Education is provisioned.
    initial_status = AgentStatus.DRAFT if purpose == AgentPurpose.EDUCATION else AgentStatus.ACTIVE
    agent = Agent(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        instructions=instructions,
        status=initial_status,
        tone=payload.tone,
        language=payload.language,
        appearance=appearance,
    )
    session.add(agent)
    try:
        await session.flush()
        await set_agent_purpose(session, agent=agent, purpose=purpose)
        session.add(
            AgentChannelBinding(
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                agent_id=agent.id,
                channel_type=payload.deployment_channel,
            )
        )
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An agent with this name already exists") from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=agent.id,
        event_type="agent.created.v1",
        payload={
            "agentId": str(agent.id),
            "workspaceId": str(principal.workspace_id),
            "channelType": payload.deployment_channel,
            "purpose": purpose.value,
        },
    )
    await session.commit()
    return await agent_response(session, agent)


@router.get("/{agent_id}", response_model=AgentOutWithPurpose)
async def get_agent(
    agent_id: UUID, principal: AgentsViewPrincipal, session: DB
) -> AgentOutWithPurpose:
    return await agent_response(
        session,
        await scoped_agent(
            session,
            principal.tenant_id,
            agent_id,
            workspace_id=principal.workspace_id,
            allowed_agent_ids=principal.agent_ids,
        ),
    )


@router.get("/{agent_id}/channel", response_model=AgentChannelOut)
async def get_agent_channel(
    agent_id: UUID,
    principal: AgentsViewPrincipal,
    session: DB,
) -> AgentChannelOut:
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    binding = await _channel_binding(session, agent)
    await session.commit()
    return AgentChannelOut(
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
        channel_type=binding.channel_type,
    )


@router.patch("/{agent_id}/channel", response_model=AgentChannelOut)
async def update_agent_channel(
    agent_id: UUID,
    payload: AgentChannelPatch,
    principal: AgentsUpdatePrincipal,
    session: DB,
) -> AgentChannelOut:
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        agent_id,
        workspace_id=principal.workspace_id,
    )
    binding = await _channel_binding(session, agent)
    binding.channel_type = payload.channel_type
    if payload.channel_type in LEGACY_APPEARANCE_CHANNELS:
        appearance = deepcopy(agent.appearance)
        appearance["deploymentChannel"] = payload.channel_type
        agent.appearance = appearance
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=agent.id,
        event_type="agent.channel.changed.v1",
        payload={
            "agentId": str(agent.id),
            "workspaceId": str(agent.workspace_id),
            "channelType": payload.channel_type,
        },
    )
    await session.commit()
    return AgentChannelOut(
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
        channel_type=binding.channel_type,
    )


@router.post("/{agent_id}/duplicate", response_model=AgentOutWithPurpose, status_code=201)
async def duplicate_agent(
    agent_id: UUID,
    payload: AgentDuplicateWithChannel,
    principal: AgentsCreatePrincipal,
    session: DB,
) -> AgentOutWithPurpose:
    source = await scoped_agent(
        session, principal.tenant_id, agent_id, workspace_id=principal.workspace_id
    )
    source_purpose = await get_agent_purpose(
        session,
        tenant_id=source.tenant_id,
        workspace_id=source.workspace_id,
        agent_id=source.id,
    )
    appearance = deepcopy(source.appearance)
    if payload.deployment_channel in LEGACY_APPEARANCE_CHANNELS:
        appearance["deploymentChannel"] = payload.deployment_channel
    duplicate = Agent(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        name=payload.name.strip(),
        description=source.description,
        instructions=source.instructions,
        status=AgentStatus.DRAFT,
        tone=source.tone,
        language=source.language,
        avatar=source.avatar,
        appearance=appearance,
        model_profile=deepcopy(source.model_profile),
        security=deepcopy(source.security),
    )
    session.add(duplicate)
    try:
        await session.flush()
        await set_agent_purpose(session, agent=duplicate, purpose=source_purpose)
        session.add(
            AgentChannelBinding(
                tenant_id=principal.tenant_id,
                workspace_id=principal.workspace_id,
                agent_id=duplicate.id,
                channel_type=payload.deployment_channel,
            )
        )
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An agent with this name already exists") from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=duplicate.id,
        event_type="agent.duplicated.v1",
        payload={
            "agentId": str(duplicate.id),
            "sourceAgentId": str(source.id),
            "workspaceId": str(principal.workspace_id),
            "deploymentChannel": payload.deployment_channel,
            "purpose": source_purpose.value,
        },
    )
    await session.commit()
    await session.refresh(duplicate)
    return await agent_response(session, duplicate)


@router.patch("/{agent_id}", response_model=AgentOutWithPurpose)
async def update_agent(
    agent_id: UUID,
    payload: AgentPatchWithPurpose,
    principal: AgentsUpdatePrincipal,
    session: DB,
) -> AgentOutWithPurpose:
    agent = await scoped_agent(
        session, principal.tenant_id, agent_id, workspace_id=principal.workspace_id
    )
    current_purpose = await get_agent_purpose(
        session,
        tenant_id=agent.tenant_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
    )
    requested_purpose = payload.purpose or current_purpose
    if payload.status == AgentStatus.ACTIVE and requested_purpose == AgentPurpose.EDUCATION:
        raise HTTPException(
            status_code=409,
            detail=(
                "Education agents remain draft until Course/Batch/Enrollment authorization is configured."
            ),
        )

    patch = payload.model_dump(exclude_unset=True)
    if "purpose" in patch:
        assert payload.purpose is not None
        await set_agent_purpose(session, agent=agent, purpose=payload.purpose)
        patch.pop("purpose")
        if payload.purpose == AgentPurpose.EDUCATION and agent.status == AgentStatus.ACTIVE:
            agent.status = AgentStatus.DRAFT
        if payload.purpose != current_purpose:
            enqueue_event(
                session,
                tenant_id=principal.tenant_id,
                aggregate_type="agent",
                aggregate_id=agent.id,
                event_type="agent.purpose.changed.v1",
                payload={
                    "agentId": str(agent.id),
                    "workspaceId": str(agent.workspace_id),
                    "previousPurpose": current_purpose.value,
                    "purpose": payload.purpose.value,
                    "status": agent.status.value,
                },
            )
    if "model" in patch:
        configured_model = get_settings().nvidia_model
        if payload.model and payload.model.model != configured_model:
            raise HTTPException(
                status_code=422, detail=f"This deployment only permits model {configured_model}"
            )
        assert payload.model is not None
        agent.model_profile = payload.model.model_dump(by_alias=True)
        patch.pop("model")
    if "appearance" in patch:
        assert payload.appearance is not None
        agent.appearance = payload.appearance.model_dump(by_alias=True)
        binding = await _channel_binding(session, agent)
        binding.channel_type = payload.appearance.deployment_channel
        patch.pop("appearance")
    if "security" in patch:
        assert payload.security is not None
        agent.security = payload.security.model_dump(by_alias=True)
        patch.pop("security")
    if "language" in patch and "appearance" not in payload.model_fields_set:
        next_appearance = deepcopy(agent.appearance)
        next_appearance.update(localized_appearance(str(patch["language"])))
        agent.appearance = next_appearance
    for name, value in patch.items():
        setattr(agent, name, value)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=agent.id,
        event_type="agent.updated.v1",
        payload={
            "agentId": str(agent.id),
            "workspaceId": str(agent.workspace_id),
            "purpose": requested_purpose.value,
            "fields": sorted(payload.model_fields_set),
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An agent with this name already exists") from None
    await session.refresh(agent)
    return await agent_response(session, agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: UUID, principal: AgentsDeletePrincipal, session: DB) -> Response:
    from datetime import UTC, datetime

    agent = await scoped_agent(
        session, principal.tenant_id, agent_id, workspace_id=principal.workspace_id
    )
    agent.deleted_at = datetime.now(UTC)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="agent",
        aggregate_id=agent.id,
        event_type="agent.deleted.v1",
        payload={"agentId": str(agent.id), "workspaceId": str(agent.workspace_id)},
    )
    await session.commit()
    return Response(status_code=204)
