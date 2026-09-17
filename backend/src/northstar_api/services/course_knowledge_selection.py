"""Resolve verified students' explicit selections; never submit processing jobs."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.course_knowledge_models import CourseEnrollmentAccess, CoursePaper, CourseStudySelection
from northstar_api.education import EducationCourse
from northstar_api.education_batches import EducationBatch
from northstar_api.services.course_knowledge import Boundary, _serialize
from northstar_api.services.course_knowledge_policy import explicit_choice, numbered_choice


@dataclass(frozen=True, slots=True)
class StudyChoice:
    enrollment: Any | None
    prompt: str | None = None


async def resolve_study_selection(session: AsyncSession, boundary: Boundary, identity_id: UUID, valid: list[Any], message: str) -> StudyChoice:
    await _serialize(session, f"course-selection:{boundary.workspace_id}:{boundary.agent_id}:{identity_id}")
    state = await session.scalar(select(CourseStudySelection).where(*boundary.filters(CourseStudySelection), CourseStudySelection.identity_id == identity_id).with_for_update())
    valid_by_id = {str(e.id): e for e in valid}
    if not valid:
        if state:
            state.enrollment_id = None
            state.menu_ids = []
            state.menu_open = False
        return StudyChoice(None)
    if state is None:
        state = CourseStudySelection(**boundary.values(), identity_id=identity_id, menu_ids=[], menu_open=False)
        session.add(state)
    # A first-use course menu has no selected enrollment yet. Preserve that menu
    # so its numeric reply can be checked against the current authorized IDs.
    # Only clear an actual remembered enrollment that is no longer valid.
    if state.enrollment_id is not None and str(state.enrollment_id) not in valid_by_id:
        state.enrollment_id = None
        state.menu_ids = []
        state.menu_open = False
    courses = (await session.scalars(select(EducationCourse).where(EducationCourse.tenant_id == boundary.tenant_id, EducationCourse.workspace_id == boundary.workspace_id, EducationCourse.id.in_({e.course_id for e in valid})))).all()
    batches = (await session.scalars(select(EducationBatch).where(EducationBatch.tenant_id == boundary.tenant_id, EducationBatch.workspace_id == boundary.workspace_id, EducationBatch.id.in_({e.batch_id for e in valid})))).all()
    course_by_id = {c.id: c for c in courses}
    batch_by_id = {b.id: b for b in batches}
    choices = sorted(valid, key=lambda e: (course_by_id[e.course_id].code, batch_by_id[e.batch_id].code, str(e.id)))
    text_value = message.strip().casefold()

    def course_menu() -> StudyChoice:
        state.menu_ids = [f"course:{e.id}" for e in choices]
        state.menu_open = True
        lines = ["Choose an active course enrollment:"]
        lines.extend(f"{i}. {course_by_id[e.course_id].name} — {batch_by_id[e.batch_id].name}" for i, e in enumerate(choices, 1))
        lines.append("Reply with a number or 'course <course code>'. Only your current enrollments are shown.")
        return StudyChoice(None, "\n".join(lines))

    course_options = [(str(e.id), [course_by_id[e.course_id].code, course_by_id[e.course_id].name, f"{course_by_id[e.course_id].code} {batch_by_id[e.batch_id].code}"]) for e in choices]
    selected = explicit_choice(message, course_options, prefix="course")
    if state.menu_open and state.menu_ids and state.menu_ids[0].startswith("course:"):
        numbered = numbered_choice(message, state.menu_ids, {f"course:{e.id}" for e in choices})
        selected = numbered.split(":", 1)[1] if numbered else selected
        if selected is None:
            return course_menu()
    if text_value in {"courses", "/courses", "change course", "switch course"}:
        return course_menu()
    if selected is None and re.match(r"^/?course\s+", text_value):
        return course_menu()
    changed = selected is not None and str(state.enrollment_id) != selected
    if selected:
        state.enrollment_id = valid_by_id[selected].id
        state.menu_open = False
        state.menu_ids = []
    if state.enrollment_id is None:
        if len(choices) != 1:
            return course_menu()
        state.enrollment_id = choices[0].id
        changed = True
    enrollment = valid_by_id[str(state.enrollment_id)]
    access = await session.scalar(select(CourseEnrollmentAccess).where(*boundary.filters(CourseEnrollmentAccess), CourseEnrollmentAccess.enrollment_id == enrollment.id, CourseEnrollmentAccess.active.is_(True)).with_for_update())
    if access is None:
        return StudyChoice(None, f"{course_by_id[enrollment.course_id].name} is selected. Your institute must configure curriculum and paper access before tutoring can begin.")
    papers = (await session.scalars(select(CoursePaper).where(CoursePaper.tenant_id == boundary.tenant_id, CoursePaper.workspace_id == boundary.workspace_id, CoursePaper.curriculum_id == access.curriculum_id, CoursePaper.id.in_([UUID(p) for p in access.paper_ids]), CoursePaper.active.is_(True)).order_by(CoursePaper.code, CoursePaper.id))).all()
    papers_by_id = {str(p.id): p for p in papers}
    if access.selected_paper_id and str(access.selected_paper_id) not in papers_by_id:
        access.selected_paper_id = None
        access.revision += 1

    def paper_menu() -> StudyChoice:
        state.menu_ids = [f"paper:{p.id}" for p in papers] + ["paper:overview"]
        state.menu_open = True
        lines = [f"Studying {course_by_id[enrollment.course_id].name}. Choose a paper:"]
        lines.extend(f"{i}. {paper.name} ({paper.code})" for i, paper in enumerate(papers, 1))
        lines.extend([f"{len(papers) + 1}. Course overview", "Reply with a number, 'paper <paper code>', or 'overview'. Send 'courses' to change courses."])
        return StudyChoice(enrollment, "\n".join(lines))

    paper_id = explicit_choice(message, [(str(p.id), [p.code, p.name]) for p in papers], prefix="paper") if text_value.startswith(("paper ", "/paper ")) else None
    overview = text_value in {"overview", "course overview"}
    if state.menu_open and state.menu_ids and state.menu_ids[0].startswith("paper:"):
        numbered = numbered_choice(message, state.menu_ids, {f"paper:{p.id}" for p in papers} | {"paper:overview"})
        if numbered:
            value = numbered.split(":", 1)[1]
            overview = value == "overview"
            paper_id = None if overview else value
        if paper_id is None and not overview and not selected:
            return paper_menu()
    if text_value in {"papers", "/papers", "change paper", "switch paper"} or (text_value.startswith(("paper ", "/paper ")) and paper_id is None):
        return paper_menu()
    if paper_id is not None or overview:
        next_paper = UUID(paper_id) if paper_id else None
        if access.selected_paper_id != next_paper:
            access.selected_paper_id = next_paper
            access.revision += 1
        state.menu_ids = []
        state.menu_open = False
        label = papers_by_id[paper_id].name if paper_id else "Course overview"
        return StudyChoice(enrollment, f"Selected: {course_by_id[enrollment.course_id].name} / {label}. Ask your question. No documents were retrained or reprocessed.")
    if selected is not None or changed:
        return paper_menu()
    return StudyChoice(enrollment)
