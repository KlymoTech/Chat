"""Create and activate immutable Education knowledge releases."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, update

from northstar_api.education_knowledge_lifecycle import (
    EducationKnowledgeRelease,
    EducationReleaseAssignment,
)
from northstar_api.education_knowledge_scope import EducationKnowledgeScope
from northstar_api.education_release_schemas import (
    EducationReleaseActivate,
    EducationReleaseCreate,
    EducationReleaseOut,
)
from northstar_api.routers.knowledge_routes import DB, KnowledgeManagePrincipal, router


@router.post("/education/knowledge/releases", response_model=EducationReleaseOut, status_code=201)
async def create_education_release(
    payload: EducationReleaseCreate,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> EducationReleaseOut:
    if len(set(payload.assignment_ids)) != len(payload.assignment_ids):
        raise HTTPException(status_code=422, detail="Release assignments must be unique")
    assignments = (
        await session.scalars(
            select(EducationKnowledgeScope).where(
                EducationKnowledgeScope.id.in_(payload.assignment_ids),
                EducationKnowledgeScope.tenant_id == principal.tenant_id,
                EducationKnowledgeScope.workspace_id == principal.workspace_id,
            )
        )
    ).all()
    if len(assignments) != len(payload.assignment_ids):
        raise HTTPException(status_code=422, detail="One or more assignments are unavailable")
    if any(
        item.agent_id != payload.agent_id
        or item.course_id != payload.course_id
        or item.curriculum_id != payload.curriculum_id
        for item in assignments
    ):
        raise HTTPException(status_code=422, detail="Every assignment must match the release tuple")
    if any(
        item.approval_status not in {"approved", "published"} or item.withdrawn_at is not None
        for item in assignments
    ):
        raise HTTPException(status_code=409, detail="Every release assignment must be approved and active")
    latest = await session.scalar(
        select(func.max(EducationKnowledgeRelease.revision)).where(
            EducationKnowledgeRelease.tenant_id == principal.tenant_id,
            EducationKnowledgeRelease.workspace_id == principal.workspace_id,
            EducationKnowledgeRelease.agent_id == payload.agent_id,
            EducationKnowledgeRelease.course_id == payload.course_id,
            EducationKnowledgeRelease.curriculum_id == payload.curriculum_id,
        )
    )
    release = EducationKnowledgeRelease(
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        agent_id=payload.agent_id,
        course_id=payload.course_id,
        curriculum_id=payload.curriculum_id,
        revision=int(latest or 0) + 1,
        status="candidate",
        manifest={"assignments": [{"id": str(item.id), "revision": item.assignment_revision} for item in assignments]},
    )
    session.add(release)
    await session.flush()
    session.add_all(
        EducationReleaseAssignment(
            release_id=release.id,
            assignment_id=item.id,
            assignment_revision=item.assignment_revision,
        )
        for item in assignments
    )
    await session.commit()
    await session.refresh(release)
    return EducationReleaseOut.model_validate(release)


@router.post("/education/knowledge/releases/{release_id}/activate", response_model=EducationReleaseOut)
async def activate_education_release(
    release_id: UUID,
    payload: EducationReleaseActivate,
    principal: KnowledgeManagePrincipal,
    session: DB,
) -> EducationReleaseOut:
    release = await session.scalar(
        select(EducationKnowledgeRelease)
        .with_for_update()
        .where(
            EducationKnowledgeRelease.id == release_id,
            EducationKnowledgeRelease.tenant_id == principal.tenant_id,
            EducationKnowledgeRelease.workspace_id == principal.workspace_id,
        )
    )
    if release is None:
        raise HTTPException(status_code=404, detail="Knowledge release not found")
    if release.status != "candidate":
        raise HTTPException(status_code=409, detail="Only a candidate release can be activated")
    if not payload.index_verified:
        raise HTTPException(status_code=409, detail="Index verification must pass before activation")
    members = (
        await session.execute(
            select(EducationReleaseAssignment, EducationKnowledgeScope)
            .join(EducationKnowledgeScope, EducationKnowledgeScope.id == EducationReleaseAssignment.assignment_id)
            .where(EducationReleaseAssignment.release_id == release.id)
        )
    ).all()
    if not members or any(
        assignment.approval_status not in {"approved", "published"}
        or assignment.withdrawn_at is not None
        or assignment.assignment_revision != membership.assignment_revision
        for membership, assignment in members
    ):
        raise HTTPException(status_code=409, detail="Release contents changed or are no longer approved")
    await session.execute(
        update(EducationKnowledgeRelease)
        .where(
            EducationKnowledgeRelease.id != release.id,
            EducationKnowledgeRelease.tenant_id == release.tenant_id,
            EducationKnowledgeRelease.workspace_id == release.workspace_id,
            EducationKnowledgeRelease.agent_id == release.agent_id,
            EducationKnowledgeRelease.course_id == release.course_id,
            EducationKnowledgeRelease.curriculum_id == release.curriculum_id,
            EducationKnowledgeRelease.status == "active",
        )
        .values(status="superseded")
    )
    now = datetime.now(UTC)
    for _, assignment in members:
        assignment.approval_status = "published"
        assignment.published_at = now
    release.status = "active"
    release.index_verified = True
    release.activated_by = principal.user_id
    release.activated_at = now
    await session.commit()
    await session.refresh(release)
    return EducationReleaseOut.model_validate(release)
