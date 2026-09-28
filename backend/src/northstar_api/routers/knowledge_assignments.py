"""Approval and publication routes for Education knowledge assignments."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.education_knowledge_lifecycle import EducationDerivedLearningArtifact
from northstar_api.education_knowledge_schemas import EducationKnowledgeScopeOut
from northstar_api.education_knowledge_scope import EducationKnowledgeScope
from northstar_api.models import KnowledgeSource, KnowledgeStatus
from northstar_api.routers.knowledge_routes import DB, KnowledgeManagePrincipal, router
from northstar_api.schemas import APIModel
from northstar_api.security import Principal


class EducationMaterialApproval(APIModel):
    extraction_revision: int = Field(ge=1)
    mapping_revision: int = Field(ge=1)


async def scoped_assignment(
    assignment_id: UUID, *, principal: Principal, session: AsyncSession, lock: bool = False
) -> EducationKnowledgeScope:
    query = select(EducationKnowledgeScope).where(
        EducationKnowledgeScope.id == assignment_id,
        EducationKnowledgeScope.tenant_id == principal.tenant_id,
        EducationKnowledgeScope.workspace_id == principal.workspace_id,
    )
    assignment = await session.scalar(query.with_for_update() if lock else query)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Education material assignment not found")
    return assignment


@router.post("/knowledge/education-assignments/{assignment_id}/approve", response_model=EducationKnowledgeScopeOut)
async def approve_education_assignment(
    assignment_id: UUID, payload: EducationMaterialApproval, principal: KnowledgeManagePrincipal, session: DB
) -> EducationKnowledgeScopeOut:
    assignment = await scoped_assignment(assignment_id, principal=principal, session=session, lock=True)
    if assignment.withdrawn_at is not None:
        raise HTTPException(status_code=409, detail="Withdrawn material cannot be approved")
    if assignment.extraction_revision != payload.extraction_revision or assignment.mapping_revision != payload.mapping_revision:
        raise HTTPException(status_code=409, detail="Content or mapping changed; review the latest revision")
    assignment.approval_status = "approved"
    assignment.approved_by = principal.user_id
    assignment.approved_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(assignment)
    return EducationKnowledgeScopeOut.model_validate(assignment)


@router.post("/knowledge/education-assignments/{assignment_id}/publish", response_model=EducationKnowledgeScopeOut)
async def publish_education_assignment(
    assignment_id: UUID, payload: EducationMaterialApproval, principal: KnowledgeManagePrincipal, session: DB
) -> EducationKnowledgeScopeOut:
    assignment = await scoped_assignment(assignment_id, principal=principal, session=session, lock=True)
    if assignment.approval_status != "approved":
        raise HTTPException(status_code=409, detail="Material must be approved before publication")
    if assignment.extraction_revision != payload.extraction_revision or assignment.mapping_revision != payload.mapping_revision:
        raise HTTPException(status_code=409, detail="Content or mapping changed; approval is no longer valid")
    if assignment.source_id is not None:
        source = await session.scalar(select(KnowledgeSource).where(KnowledgeSource.id == assignment.source_id, KnowledgeSource.status == KnowledgeStatus.READY))
        if source is None:
            raise HTTPException(status_code=409, detail="Source processing and indexing are not complete")
    assignment.approval_status = "published"
    assignment.published_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(assignment)
    return EducationKnowledgeScopeOut.model_validate(assignment)


@router.post("/knowledge/education-assignments/{assignment_id}/withdraw", response_model=EducationKnowledgeScopeOut)
async def withdraw_education_assignment(
    assignment_id: UUID, principal: KnowledgeManagePrincipal, session: DB
) -> EducationKnowledgeScopeOut:
    assignment = await scoped_assignment(assignment_id, principal=principal, session=session, lock=True)
    assignment.approval_status = "withdrawn"
    assignment.withdrawn_at = datetime.now(UTC)
    artifacts = (await session.scalars(select(EducationDerivedLearningArtifact).where(EducationDerivedLearningArtifact.tenant_id == principal.tenant_id, EducationDerivedLearningArtifact.workspace_id == principal.workspace_id, EducationDerivedLearningArtifact.agent_id == assignment.agent_id, EducationDerivedLearningArtifact.publication_status != "withdrawn"))).all()
    assignment_key = str(assignment.id)
    for artifact in artifacts:
        if assignment_key in artifact.course_assignment_ids:
            artifact.publication_status = "withdrawn"
    await session.commit()
    await session.refresh(assignment)
    return EducationKnowledgeScopeOut.model_validate(assignment)
