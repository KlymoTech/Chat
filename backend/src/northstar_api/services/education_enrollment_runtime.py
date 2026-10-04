from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.course_knowledge_models import CourseStudySelection
from northstar_api.education_student_identities import EducationStudentIdentity
from northstar_api.education_tutor import EducationTutorContext


async def invalidate_enrollment_runtime_state(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    student_id: UUID,
    enrollment_id: UUID,
) -> None:
    """Remove a changed enrollment from remembered course menus/selections.

    Conversations are retained for audit. The next incoming message must resolve
    the current enrollment set again, so revoked or altered access cannot be
    reused through a cached course choice.
    """
    tutors = (
        await session.scalars(
            select(EducationTutorContext)
            .where(
                EducationTutorContext.tenant_id == tenant_id,
                EducationTutorContext.workspace_id == workspace_id,
                EducationTutorContext.student_id == student_id,
            )
            .with_for_update()
        )
    ).all()
    for tutor in tutors:
        changed = False
        if tutor.active_enrollment_id == enrollment_id:
            tutor.active_enrollment_id = None
            tutor.active_paper_id = None
            changed = True
        if str(enrollment_id) in (tutor.pending_enrollment_ids or []):
            tutor.pending_enrollment_ids = [item for item in tutor.pending_enrollment_ids if item != str(enrollment_id)]
            changed = True
        if changed:
            tutor.interaction_state = "ready_for_question"
            tutor.pending_question = None
            tutor.selection_revision += 1

    identity_ids = list(
        await session.scalars(
            select(EducationStudentIdentity.id).where(
                EducationStudentIdentity.tenant_id == tenant_id,
                EducationStudentIdentity.workspace_id == workspace_id,
                EducationStudentIdentity.student_id == student_id,
            )
        )
    )
    if not identity_ids:
        return
    selections = (
        await session.scalars(
            select(CourseStudySelection)
            .where(
                CourseStudySelection.tenant_id == tenant_id,
                CourseStudySelection.workspace_id == workspace_id,
                CourseStudySelection.identity_id.in_(identity_ids),
            )
            .with_for_update()
        )
    ).all()
    token = f"course:{enrollment_id}"
    for selection in selections:
        changed = False
        if selection.enrollment_id == enrollment_id:
            selection.enrollment_id = None
            changed = True
        if token in (selection.menu_ids or []):
            selection.menu_ids = [item for item in selection.menu_ids if item != token]
            changed = True
        if changed:
            selection.menu_open = False
            selection.menu_id = None
            selection.menu_created_at = None
            selection.menu_expires_at = None
            selection.interaction_state = "ready_for_question"
            selection.pending_question = None
            selection.selection_revision += 1
