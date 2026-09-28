"""Education-scope routes for knowledge sources."""

from __future__ import annotations

from uuid import UUID

from northstar_api.education_knowledge_schemas import (
    EducationKnowledgeScopeOut,
    EducationKnowledgeScopeReplace,
)
from northstar_api.routers.knowledge_routes import (
    DB,
    KnowledgeManagePrincipal,
    KnowledgeViewPrincipal,
    router,
)
from northstar_api.routers.knowledge_support import scoped_source
from northstar_api.services.education_knowledge import list_source_scopes, replace_source_scopes
from northstar_api.services.outbox import enqueue_event


@router.get(
    "/knowledge/{source_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def get_source_education_scopes(
    source_id: UUID,
    principal: KnowledgeViewPrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    source = await scoped_source(source_id, principal=principal, session=session)
    return list(
        await list_source_scopes(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            agent_id=source.agent_id,
            source_id=source.id,
        )
    )


@router.put(
    "/knowledge/{source_id}/education-scopes",
    response_model=list[EducationKnowledgeScopeOut],
)
async def set_source_education_scopes(
    source_id: UUID,
    payload: EducationKnowledgeScopeReplace,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> list[EducationKnowledgeScopeOut]:
    source = await scoped_source(source_id, principal=principal, session=session)
    scopes = await replace_source_scopes(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=source.agent_id,
        source_id=source.id,
        pairs=payload.scopes,
    )
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="knowledge_source",
        aggregate_id=source.id,
        event_type="education.knowledge.scope.updated.v1",
        payload={
            "sourceId": str(source.id),
            "agentId": str(source.agent_id),
            "scopes": [{"courseId": str(item.course_id), "batchId": str(item.batch_id)} for item in scopes],
        },
    )
    await session.commit()
    return list(scopes)
