"""Knowledge-fact routes kept separate from source-ingestion routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.education_knowledge_schemas import (
    EducationKnowledgeScopeOut,
    EducationKnowledgeScopeReplace,
)
from northstar_api.models import FactStatus, KnowledgeFact
from northstar_api.routers.agents import scoped_agent
from northstar_api.routers.knowledge_routes import (
    DB,
    KnowledgeManagePrincipal,
    KnowledgeViewPrincipal,
    router,
)
from northstar_api.schemas import FactCreate, FactOut, FactPatch
from northstar_api.security import Principal
from northstar_api.services.education_knowledge import (
    list_fact_scopes,
    replace_fact_scopes,
    require_education_agent,
)
from northstar_api.services.llm import nvidia_adapter
from northstar_api.services.outbox import enqueue_event


@router.get("/agents/{agent_id}/facts", response_model=list[FactOut])
async def list_facts(
    agent_id: UUID,
    principal: KnowledgeViewPrincipal,
    session: DB,
    fact_status: FactStatus | None = None,
) -> list[KnowledgeFact]:
    await scoped_agent(
        session,
        principal.tenant_id,
        agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    query = select(KnowledgeFact).where(
        KnowledgeFact.tenant_id == principal.tenant_id,
        KnowledgeFact.workspace_id == principal.workspace_id,
        KnowledgeFact.agent_id == agent_id,
    )
    if fact_status:
        query = query.where(KnowledgeFact.status == fact_status)
    return list((await session.scalars(query.order_by(KnowledgeFact.updated_at.desc()))).all())


@router.post("/agents/{agent_id}/facts", response_model=FactOut, status_code=201)
async def create_fact(
    agent_id: UUID,
    payload: FactCreate,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> KnowledgeFact:
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    vector = await nvidia_adapter.embed_query(f"{payload.question}\n{payload.answer}")
    fact = KnowledgeFact(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=agent_id,
        question=payload.question.strip(),
        answer=payload.answer.strip(),
        status=payload.status,
        priority=payload.priority,
        revision=agent.published_knowledge_revision,
        embedding_model=get_settings().nvidia_embedding_model,
        embedding=vector,
        approved_by=principal.user_id if payload.status == FactStatus.APPROVED else None,
        approved_at=datetime.now(UTC) if payload.status == FactStatus.APPROVED else None,
    )
    session.add(fact)
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_fact",
        aggregate_id=fact.id,
        event_type="knowledge.fact.changed.v1",
        payload={"factId": str(fact.id), "agentId": str(agent_id), "status": fact.status.value},
    )
    await session.commit()
    await session.refresh(fact)
    return fact


async def scoped_fact(
    fact_id: UUID,
    *,
    principal: Principal,
    session: AsyncSession,
) -> KnowledgeFact:
    """Load a fact visible to the principal and verify its Education agent."""
    fact = await session.scalar(
        select(KnowledgeFact).where(
            KnowledgeFact.id == fact_id,
            KnowledgeFact.tenant_id == principal.tenant_id,
            KnowledgeFact.workspace_id == principal.workspace_id,
        )
    )
    if fact is None:
        raise HTTPException(status_code=404, detail="Knowledge fact not found")
    agent = await scoped_agent(
        session,
        principal.tenant_id,
        fact.agent_id,
        workspace_id=principal.workspace_id,
        allowed_agent_ids=principal.agent_ids,
    )
    await require_education_agent(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent=agent,
    )
    return fact


@router.get(
    "/facts/{fact_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def get_fact_education_scopes(
    fact_id: UUID,
    principal: KnowledgeViewPrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    fact = await scoped_fact(fact_id, principal=principal, session=session)
    return list(
        await list_fact_scopes(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent_id=fact.agent_id,
            fact_id=fact.id,
        )
    )


@router.put(
    "/facts/{fact_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def set_fact_education_scopes(
    fact_id: UUID,
    payload: EducationKnowledgeScopeReplace,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    fact = await scoped_fact(fact_id, principal=principal, session=session)
    scopes = await replace_fact_scopes(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=fact.agent_id,
        fact_id=fact.id,
        pairs=payload.scopes,
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_fact",
        aggregate_id=fact.id,
        event_type="education.knowledge.scope.updated.v1",
        payload={
            "factId": str(fact.id),
            "agentId": str(fact.agent_id),
            "scopes": [{"courseId": str(item.course_id), "batchId": str(item.batch_id)} for item in scopes],
        },
    )
    await session.commit()
    return list(scopes)


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def update_fact(
    fact_id: UUID,
    payload: FactPatch,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> KnowledgeFact:
    fact = await session.scalar(
        select(KnowledgeFact).where(
            KnowledgeFact.id == fact_id,
            KnowledgeFact.tenant_id == principal.tenant_id,
            KnowledgeFact.workspace_id == principal.workspace_id,
        )
    )
    if fact is None:
        raise HTTPException(status_code=404, detail="Knowledge fact not found")
    patch = payload.model_dump(exclude_unset=True)
    for name, value in patch.items():
        setattr(fact, name, value)
    if "status" in patch and fact.status == FactStatus.APPROVED:
        fact.approved_by = principal.user_id
        fact.approved_at = datetime.now(UTC)
    if {"question", "answer"} & patch.keys():
        fact.embedding = await nvidia_adapter.embed_query(f"{fact.question}\n{fact.answer}")
        fact.embedding_model = get_settings().nvidia_embedding_model
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_fact",
        aggregate_id=fact.id,
        event_type="knowledge.fact.changed.v1",
        payload={"factId": str(fact.id), "agentId": str(fact.agent_id), "status": fact.status.value},
    )
    await session.commit()
    await session.refresh(fact)
    return fact
