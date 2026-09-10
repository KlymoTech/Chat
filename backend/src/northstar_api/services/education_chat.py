from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.models import Agent, Channel, Conversation, ConversationState
from northstar_api.schemas import ChatStreamRequest
from northstar_api.services.chat import ChatCoordinator, PreparedChat
from northstar_api.services.education_rag import (
    EducationRagAccessDenied,
    authorized_education_retrieval_scope,
)
from northstar_api.services.retrieval import (
    EducationRetrievalScope,
    Evidence,
    RetrievalService,
    retrieval_service,
)

_education_scope: ContextVar[EducationRetrievalScope | None] = ContextVar(
    "education_retrieval_scope",
    default=None,
)


class EducationScopedRetrieval(RetrievalService):
    """Reuse the existing retrieval service while injecting Education authorization."""

    def __init__(self, base: RetrievalService) -> None:
        self.base = base
        self.model = base.model
        self.settings = base.settings

    async def retrieve(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent_id: UUID,
        revision: int,
        query: str,
        education_scope: EducationRetrievalScope | None = None,
    ) -> list[Evidence]:
        agent = await session.scalar(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.tenant_id == tenant_id,
            )
        )
        if agent is None:
            return []
        purpose = await get_agent_purpose(
            session,
            tenant_id=tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
        )
        scope = education_scope
        if purpose is AgentPurpose.EDUCATION:
            scope = scope or _education_scope.get()
            if scope is None:
                raise EducationRagAccessDenied("education_context_missing")
        return await self.base.retrieve(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            revision=revision,
            query=query,
            education_scope=scope,
        )


class EducationAwareChatCoordinator(ChatCoordinator):
    """Keep legacy chat behavior while fail-closing Education conversations."""

    async def prepare(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        workspace_id: UUID | None = None,
        allowed_agent_ids: frozenset[UUID] | None = None,
        request: ChatStreamRequest,
        channel: Channel = Channel.WIDGET,
    ) -> PreparedChat:
        token = _education_scope.set(None)
        try:
            return await super().prepare(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                allowed_agent_ids=allowed_agent_ids,
                request=request,
                channel=channel,
            )
        finally:
            _education_scope.reset(token)

    async def _get_or_create_conversation(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent: Agent,
        request: ChatStreamRequest,
        channel: Channel,
    ) -> Conversation:
        purpose = await get_agent_purpose(
            session,
            tenant_id=tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
        )
        if purpose is not AgentPurpose.EDUCATION:
            return await super()._get_or_create_conversation(
                session,
                tenant_id=tenant_id,
                agent=agent,
                request=request,
                channel=channel,
            )

        if request.conversation_id is None:
            raise HTTPException(
                status_code=403,
                detail="Education access must be authorized before starting chat",
            )
        conditions = [Conversation.public_id == str(request.conversation_id)]
        try:
            conditions.append(Conversation.id == UUID(str(request.conversation_id)))
        except ValueError:
            pass
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.workspace_id == agent.workspace_id,
                Conversation.agent_id == agent.id,
                Conversation.state == ConversationState.OPEN,
                or_(*conditions),
            )
        )
        if conversation is None:
            raise HTTPException(status_code=403, detail="Education conversation is not authorized")
        try:
            scope = await authorized_education_retrieval_scope(
                session,
                tenant_id=tenant_id,
                workspace_id=agent.workspace_id,
                agent=agent,
                conversation_id=conversation.id,
            )
        except EducationRagAccessDenied:
            raise HTTPException(
                status_code=403,
                detail="Education access is no longer authorized for this conversation",
            ) from None
        _education_scope.set(scope)
        return conversation


education_chat_coordinator = EducationAwareChatCoordinator(
    retrieval=EducationScopedRetrieval(retrieval_service)
)
