from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.database import get_session
from northstar_api.dependencies import require_permissions
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_schemas import CourseCreate, CourseOut, CoursePatch
from northstar_api.models import Agent, AgentStatus
from northstar_api.security import Principal
from northstar_api.services.education_enrollment import has_non_terminal_enrollment
from northstar_api.services.outbox import enqueue_event

router = APIRouter(prefix="/education/courses", tags=["education"])
DB = Annotated[AsyncSession, Depends(get_session)]
EducationViewPrincipal = Annotated[Principal, Depends(require_permissions("education.view"))]
EducationManagePrincipal = Annotated[Principal, Depends(require_permissions("education.manage"))]


def _workspace_id(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace access is unavailable")
    return principal.workspace_id


async def _scoped_course(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    course_id: UUID,
) -> EducationCourse:
    course = await session.scalar(
        select(EducationCourse).where(
            EducationCourse.id == course_id,
            EducationCourse.tenant_id == tenant_id,
            EducationCourse.workspace_id == workspace_id,
        )
    )
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


async def _ensure_course_has_no_active_batches(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    course_id: UUID,
) -> None:
    active_batch_id = await session.scalar(
        select(EducationBatch.id)
        .where(
            EducationBatch.tenant_id == tenant_id,
            EducationBatch.workspace_id == workspace_id,
            EducationBatch.course_id == course_id,
            EducationBatch.status == BatchStatus.ACTIVE.value,
        )
        .limit(1)
    )
    if active_batch_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Archive active batches before archiving this course",
        )


async def _ensure_course_has_no_live_enrollments(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    course_id: UUID,
) -> None:
    if await has_non_terminal_enrollment(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        course_id=course_id,
    ):
        raise HTTPException(
            status_code=409,
            detail="Resolve non-terminal Enrollments before archiving this Course",
        )


def _course_out(course: EducationCourse) -> CourseOut:
    return CourseOut.model_validate(course)


async def _validate_simplified_agent(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, agent_id: UUID, excluding_course_id: UUID | None = None
) -> None:
    agent = await session.scalar(select(Agent).where(
        Agent.id == agent_id, Agent.tenant_id == tenant_id, Agent.workspace_id == workspace_id,
        Agent.deleted_at.is_(None), Agent.status.in_([AgentStatus.DRAFT, AgentStatus.ACTIVE]),
    ))
    if agent is None:
        raise HTTPException(status_code=422, detail="Assigned Agent must be an active or draft workspace Agent")
    if await get_agent_purpose(session, tenant_id=tenant_id, workspace_id=workspace_id, agent_id=agent.id) is not AgentPurpose.EDUCATION:
        raise HTTPException(status_code=422, detail="Assigned Agent must have Education purpose")
    # A domain Education Agent may serve several simplified Courses. Runtime
    # retrieval stays constrained by the student's selected enrollment/course.


async def _validate_channel_connections(session: AsyncSession, *, tenant_id: UUID, ids: list[UUID]) -> None:
    if not ids:
        return
    from northstar_api.lead_crm.channel_models import ChannelConnection
    found = set(await session.scalars(select(ChannelConnection.id).where(
        ChannelConnection.tenant_id == tenant_id, ChannelConnection.id.in_(ids),
        ChannelConnection.status != "disabled",
    )))
    if found != set(ids):
        raise HTTPException(status_code=422, detail="Every allowed channel connection must be active in this tenant")


@router.get("", response_model=list[CourseOut])
async def list_courses(
    principal: EducationViewPrincipal,
    session: DB,
    course_status: CourseStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=120),
) -> list[CourseOut]:
    workspace_id = _workspace_id(principal)
    conditions = [
        EducationCourse.tenant_id == principal.tenant_id,
        EducationCourse.workspace_id == workspace_id,
    ]
    if course_status is not None:
        conditions.append(EducationCourse.status == course_status.value)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                EducationCourse.code.ilike(pattern),
                EducationCourse.name.ilike(pattern),
                EducationCourse.description.ilike(pattern),
            )
        )
    courses = (
        await session.scalars(
            select(EducationCourse)
            .where(*conditions)
            .order_by(EducationCourse.status, EducationCourse.name, EducationCourse.code)
        )
    ).all()
    return [_course_out(course) for course in courses]


@router.post("", response_model=CourseOut, status_code=201)
async def create_course(
    payload: CourseCreate,
    principal: EducationManagePrincipal,
    session: DB,
) -> CourseOut:
    workspace_id = _workspace_id(principal)
    if payload.simplified_workflow:
        if payload.assigned_agent_id is None:
            raise HTTPException(status_code=422, detail="A simplified Course requires an assigned Education Agent")
        await _validate_simplified_agent(session, tenant_id=principal.tenant_id, workspace_id=workspace_id, agent_id=payload.assigned_agent_id)
        await _validate_channel_connections(session, tenant_id=principal.tenant_id, ids=payload.allowed_channel_connection_ids)
    course = EducationCourse(
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        code=payload.code,
        name=payload.name,
        awarding_body=payload.awarding_body,
        jurisdiction=payload.jurisdiction,
        aliases=payload.aliases,
        description=payload.description,
        simplified_workflow=payload.simplified_workflow,
        assigned_agent_id=payload.assigned_agent_id,
        allowed_channel_connection_ids=[str(item) for item in payload.allowed_channel_connection_ids],
        status=CourseStatus.ACTIVE.value,
    )
    session.add(course)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A course with this code already exists in this workspace",
        ) from None
    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_course",
        aggregate_id=course.id,
        event_type="education.course.created.v1",
        payload={
            "courseId": str(course.id),
            "workspaceId": str(workspace_id),
            "code": course.code,
            "name": course.name,
        },
    )
    await session.commit()
    await session.refresh(course)
    return _course_out(course)


@router.get("/{course_id}", response_model=CourseOut)
async def get_course(
    course_id: UUID,
    principal: EducationViewPrincipal,
    session: DB,
) -> CourseOut:
    return _course_out(
        await _scoped_course(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=_workspace_id(principal),
            course_id=course_id,
        )
    )


@router.patch("/{course_id}", response_model=CourseOut)
async def update_course(
    course_id: UUID,
    payload: CoursePatch,
    principal: EducationManagePrincipal,
    session: DB,
) -> CourseOut:
    workspace_id = _workspace_id(principal)
    course = await _scoped_course(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        course_id=course_id,
    )
    previous_agent_id = course.assigned_agent_id
    next_simplified = payload.simplified_workflow if payload.simplified_workflow is not None else course.simplified_workflow
    next_agent_id = payload.assigned_agent_id if "assigned_agent_id" in payload.model_fields_set else course.assigned_agent_id
    if next_simplified:
        if next_agent_id is None:
            raise HTTPException(status_code=422, detail="A simplified Course requires an assigned Education Agent")
        if course.simplified_workflow and course.assigned_agent_id and next_agent_id != course.assigned_agent_id and not payload.confirm_agent_reassignment:
            raise HTTPException(status_code=409, detail="Confirm Education Agent reassignment before changing the simplified Course tutor")
        await _validate_simplified_agent(session, tenant_id=principal.tenant_id, workspace_id=workspace_id, agent_id=next_agent_id, excluding_course_id=course.id)
    if payload.allowed_channel_connection_ids is not None:
        await _validate_channel_connections(session, tenant_id=principal.tenant_id, ids=payload.allowed_channel_connection_ids)
    if payload.status == CourseStatus.ARCHIVED and course.status != CourseStatus.ARCHIVED.value:
        await _ensure_course_has_no_live_enrollments(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=course.id,
        )
        await _ensure_course_has_no_active_batches(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=course.id,
        )

    changed_fields: list[str] = []
    for field_name in payload.model_fields_set:
        if field_name == "confirm_agent_reassignment":
            continue
        value = getattr(payload, field_name)
        if value is None:
            continue
        if field_name == "status":
            value = value.value
        elif field_name == "allowed_channel_connection_ids":
            value = [str(item) for item in value]
        if getattr(course, field_name) == value:
            continue
        setattr(course, field_name, value)
        changed_fields.append(field_name)

    if not changed_fields:
        return _course_out(course)

    enqueue_event(
        session,
        tenant_id=principal.tenant_id,
        aggregate_type="education_course",
        aggregate_id=course.id,
        event_type="education.course.updated.v1",
        payload={
            "courseId": str(course.id),
            "workspaceId": str(course.workspace_id),
            "fields": sorted(changed_fields),
            "status": course.status,
        },
    )
    if "assigned_agent_id" in changed_fields:
        enqueue_event(
            session, tenant_id=principal.tenant_id, aggregate_type="education_course", aggregate_id=course.id,
            event_type="education.course.agent_reassigned.v1",
            payload={"courseId": str(course.id), "workspaceId": str(workspace_id), "oldAgentId": str(previous_agent_id) if previous_agent_id else None, "newAgentId": str(next_agent_id)},
        )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A course with this code already exists in this workspace",
        ) from None
    await session.refresh(course)
    return _course_out(course)


@router.delete("/{course_id}", status_code=204)
async def archive_course(
    course_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    workspace_id = _workspace_id(principal)
    course = await _scoped_course(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        course_id=course_id,
    )
    if course.status != CourseStatus.ARCHIVED.value:
        await _ensure_course_has_no_live_enrollments(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=course.id,
        )
        await _ensure_course_has_no_active_batches(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            course_id=course.id,
        )
        course.status = CourseStatus.ARCHIVED.value
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="education_course",
            aggregate_id=course.id,
            event_type="education.course.archived.v1",
            payload={
                "courseId": str(course.id),
                "workspaceId": str(course.workspace_id),
                "code": course.code,
            },
        )
        await session.commit()
    return Response(status_code=204)


@router.delete("/{course_id}/permanent", status_code=204)
async def permanently_delete_course(
    course_id: UUID,
    principal: EducationManagePrincipal,
    session: DB,
) -> Response:
    """Permanently remove a Course and its course-owned access records."""
    workspace_id = _workspace_id(principal)
    course = await _scoped_course(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        course_id=course_id,
    )

    # These tables use restrictive foreign keys so regular enrollment changes
    # never erase history. A confirmed Course deletion removes this Course's
    # dependent authorization data first, while retaining shared resources.
    from northstar_api.course_knowledge_models import (
        CourseAcademicReview,
        CourseBatchCurriculum,
        CourseFaqEntry,
        CourseKnowledgeRelease,
        CourseMaterialAssignment,
        CourseReleaseHead,
        CourseWhatsappTurn,
    )
    from northstar_api.education_conversation_context import EducationConversationContext
    from northstar_api.education_enrollment_events import EducationEnrollmentEvent
    from northstar_api.education_enrollments import EducationEnrollment
    from northstar_api.education_knowledge_lifecycle import EducationKnowledgeRelease
    from northstar_api.education_knowledge_scope import EducationKnowledgeScope
    from northstar_api.education_student_activity import EducationStudentActivityEvent
    from northstar_api.education_tutor import EducationAcademicReview

    enrollment_ids = select(EducationEnrollment.id).where(
        EducationEnrollment.tenant_id == principal.tenant_id,
        EducationEnrollment.workspace_id == workspace_id,
        EducationEnrollment.course_id == course.id,
    )
    batch_ids = select(EducationBatch.id).where(
        EducationBatch.tenant_id == principal.tenant_id,
        EducationBatch.workspace_id == workspace_id,
        EducationBatch.course_id == course.id,
    )

    try:
        await session.execute(delete(EducationConversationContext).where(
            EducationConversationContext.tenant_id == principal.tenant_id,
            EducationConversationContext.workspace_id == workspace_id,
            EducationConversationContext.course_id == course.id,
        ))
        await session.execute(delete(EducationStudentActivityEvent).where(
            EducationStudentActivityEvent.tenant_id == principal.tenant_id,
            EducationStudentActivityEvent.workspace_id == workspace_id,
            EducationStudentActivityEvent.course_id == course.id,
        ))
        await session.execute(delete(EducationEnrollmentEvent).where(
            EducationEnrollmentEvent.tenant_id == principal.tenant_id,
            EducationEnrollmentEvent.workspace_id == workspace_id,
            EducationEnrollmentEvent.enrollment_id.in_(enrollment_ids),
        ))

        await session.execute(delete(CourseWhatsappTurn).where(
            CourseWhatsappTurn.tenant_id == principal.tenant_id,
            CourseWhatsappTurn.workspace_id == workspace_id,
            CourseWhatsappTurn.course_id == course.id,
        ))
        await session.execute(delete(CourseFaqEntry).where(
            CourseFaqEntry.tenant_id == principal.tenant_id,
            CourseFaqEntry.workspace_id == workspace_id,
            CourseFaqEntry.course_id == course.id,
        ))
        await session.execute(delete(CourseAcademicReview).where(
            CourseAcademicReview.tenant_id == principal.tenant_id,
            CourseAcademicReview.workspace_id == workspace_id,
            CourseAcademicReview.course_id == course.id,
        ))
        await session.execute(delete(CourseReleaseHead).where(
            CourseReleaseHead.tenant_id == principal.tenant_id,
            CourseReleaseHead.workspace_id == workspace_id,
            CourseReleaseHead.course_id == course.id,
        ))
        await session.execute(delete(CourseKnowledgeRelease).where(
            CourseKnowledgeRelease.tenant_id == principal.tenant_id,
            CourseKnowledgeRelease.workspace_id == workspace_id,
            CourseKnowledgeRelease.course_id == course.id,
        ))
        await session.execute(delete(CourseMaterialAssignment).where(
            CourseMaterialAssignment.tenant_id == principal.tenant_id,
            CourseMaterialAssignment.workspace_id == workspace_id,
            CourseMaterialAssignment.course_id == course.id,
        ))
        await session.execute(delete(CourseBatchCurriculum).where(
            CourseBatchCurriculum.tenant_id == principal.tenant_id,
            CourseBatchCurriculum.workspace_id == workspace_id,
            CourseBatchCurriculum.batch_id.in_(batch_ids),
        ))
        await session.execute(delete(EducationAcademicReview).where(
            EducationAcademicReview.tenant_id == principal.tenant_id,
            EducationAcademicReview.workspace_id == workspace_id,
            EducationAcademicReview.course_id == course.id,
        ))
        await session.execute(delete(EducationKnowledgeRelease).where(
            EducationKnowledgeRelease.tenant_id == principal.tenant_id,
            EducationKnowledgeRelease.workspace_id == workspace_id,
            EducationKnowledgeRelease.course_id == course.id,
        ))
        await session.execute(delete(EducationKnowledgeScope).where(
            EducationKnowledgeScope.tenant_id == principal.tenant_id,
            EducationKnowledgeScope.workspace_id == workspace_id,
            EducationKnowledgeScope.course_id == course.id,
        ))

        enrollment_delete = await session.execute(delete(EducationEnrollment).where(
            EducationEnrollment.tenant_id == principal.tenant_id,
            EducationEnrollment.workspace_id == workspace_id,
            EducationEnrollment.course_id == course.id,
        ))
        batch_delete = await session.execute(delete(EducationBatch).where(
            EducationBatch.tenant_id == principal.tenant_id,
            EducationBatch.workspace_id == workspace_id,
            EducationBatch.course_id == course.id,
        ))

        course_code, course_name = course.code, course.name
        await session.delete(course)
        enqueue_event(
            session,
            tenant_id=principal.tenant_id,
            aggregate_type="education_course",
            aggregate_id=course_id,
            event_type="education.course.deleted.v1",
            payload={
                "courseId": str(course_id),
                "workspaceId": str(workspace_id),
                "code": course_code,
                "name": course_name,
                "deletedEnrollmentCount": enrollment_delete.rowcount or 0,
                "deletedBatchCount": batch_delete.rowcount or 0,
            },
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Course could not be deleted because protected related records remain",
        ) from None
    except Exception:
        await session.rollback()
        raise
    return Response(status_code=204)
