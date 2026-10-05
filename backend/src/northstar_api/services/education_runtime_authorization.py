from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.education import CourseStatus, EducationCourse
from northstar_api.education_batches import BatchStatus, EducationBatch
from northstar_api.education_enrollments import EducationEnrollment, EnrollmentStatus
from northstar_api.education_students import EducationStudent
from northstar_api.education_student_identities import StudentIdentityType
from northstar_api.education_tutor import EducationTutorContext
from northstar_api.lead_crm.channels import CanonicalInboundEvent
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Agent, AgentStatus
from northstar_api.services.student_identity import find_workspace_student_identity
from northstar_api.services.workspace_dates import workspace_today


class EducationAccessReason(str, enum.Enum):
    AUTHORIZED = "authorized"
    FEATURE_DISABLED = "feature_disabled"
    UNSUPPORTED_CHANNEL = "unsupported_channel"
    UNTRUSTED_CHANNEL = "untrusted_channel"
    CHANNEL_SCOPE_MISMATCH = "channel_scope_mismatch"
    IDENTITY_MISSING = "identity_missing"
    IDENTITY_INVALID = "identity_invalid"
    IDENTITY_NOT_VERIFIED = "identity_not_verified"
    AGENT_SCOPE_MISMATCH = "agent_scope_mismatch"
    AGENT_INACTIVE = "agent_inactive"
    AGENT_NOT_EDUCATION = "agent_not_education"
    ENROLLMENT_NOT_FOUND = "enrollment_not_found"
    ENROLLMENT_AMBIGUOUS = "enrollment_ambiguous"
    ENROLLMENT_CONFIGURATION_CONFLICT = "enrollment_configuration_conflict"
    COURSE_NOT_ENROLLED = "course_not_enrolled"
    ENROLLMENT_PENDING = "enrollment_pending"
    ENROLLMENT_SUSPENDED = "enrollment_suspended"
    ENROLLMENT_EXPIRED = "enrollment_expired"
    ENROLLMENT_REVOKED = "enrollment_revoked"
    ENROLLMENT_GRADUATED = "enrollment_graduated"
    COURSE_INACTIVE = "course_inactive"
    BATCH_INACTIVE = "batch_inactive"
    BATCH_NOT_STARTED = "batch_not_started"
    BATCH_ENDED = "batch_ended"
    ACCESS_NOT_STARTED = "access_not_started"
    ACCESS_ENDED = "access_ended"


@dataclass(frozen=True, slots=True)
class EducationIdentityCandidate:
    identity_type: StudentIdentityType
    identifier: str


@dataclass(frozen=True, slots=True)
class EducationAccessDecision:
    authorized: bool
    reason: EducationAccessReason
    agent_id: UUID
    workspace_id: UUID
    identity_id: UUID | None = None
    student_id: UUID | None = None
    enrollment_id: UUID | None = None
    course_id: UUID | None = None
    batch_id: UUID | None = None

    def event_payload(self) -> dict[str, str | bool | None]:
        return {
            "authorized": self.authorized,
            "reason": self.reason.value,
            "agentId": str(self.agent_id),
            "workspaceId": str(self.workspace_id),
            "identityId": str(self.identity_id) if self.identity_id else None,
            "studentId": str(self.student_id) if self.student_id else None,
            "enrollmentId": str(self.enrollment_id) if self.enrollment_id else None,
            "courseId": str(self.course_id) if self.course_id else None,
            "batchId": str(self.batch_id) if self.batch_id else None,
        }


@dataclass(frozen=True, slots=True)
class SharedEducationRoute:
    """Result for a reusable channel serving simplified Courses.

    The gateway Agent owns only the short-lived menu state.  The returned
    target Agent owns the actual conversation and retrieval boundary.
    """
    decision: EducationAccessDecision
    target_agent: Agent | None
    # Control turns never enter the tutoring/retrieval path.
    notice: str | None = None


_CHAT_START_MESSAGES = {"/start", "start"}
_GREETING_MESSAGES = {
    "hi", "hello", "hey", "hiya", "good morning", "good afternoon", "good evening",
}
_COURSE_MENU_MESSAGES = {"courses", "switch course", "switch courses"}


def identity_candidate_for_event(
    event: CanonicalInboundEvent,
    *,
    allow_unsigned_widget: bool = False,
) -> tuple[EducationIdentityCandidate | None, EducationAccessReason | None]:
    """Map a normalized inbound channel identity onto the Education identity model.

    Education access is intentionally fail-closed. Only channels with a first-class
    Student identity type are accepted here. Additional channel types must define an
    explicit identity contract before they can enter the Education runtime.
    """

    if event.provider is ChannelProvider.WHATSAPP:
        raw = event.sender.phone or event.sender.external_id
        if not raw:
            return None, EducationAccessReason.IDENTITY_MISSING
        identifier = raw.strip()
        if identifier.isdigit():
            identifier = f"+{identifier}"
        return EducationIdentityCandidate(StudentIdentityType.WHATSAPP, identifier), None

    if event.provider is ChannelProvider.TELEGRAM:
        if not event.sender.external_id:
            return None, EducationAccessReason.IDENTITY_MISSING
        return (
            EducationIdentityCandidate(StudentIdentityType.TELEGRAM, event.sender.external_id.strip()),
            None,
        )

    if event.provider is ChannelProvider.WIDGET:
        if allow_unsigned_widget:
            return None, EducationAccessReason.UNTRUSTED_CHANNEL
        if not event.sender.external_id:
            return None, EducationAccessReason.IDENTITY_MISSING
        return (
            EducationIdentityCandidate(
                StudentIdentityType.WEBSITE_LOGIN,
                event.sender.external_id.strip(),
            ),
            None,
        )

    return None, EducationAccessReason.UNSUPPORTED_CHANNEL


def _decision(
    *,
    authorized: bool,
    reason: EducationAccessReason,
    agent: Agent,
    identity_id: UUID | None = None,
    student_id: UUID | None = None,
    enrollment: EducationEnrollment | None = None,
) -> EducationAccessDecision:
    return EducationAccessDecision(
        authorized=authorized,
        reason=reason,
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
        identity_id=identity_id,
        student_id=student_id,
        enrollment_id=enrollment.id if enrollment else None,
        course_id=enrollment.course_id if enrollment else None,
        batch_id=enrollment.batch_id if enrollment else None,
    )


async def _active_enrollment_denial_reason(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    enrollment: EducationEnrollment,
    as_of: date,
) -> EducationAccessReason | None:
    course_status = await session.scalar(
        select(EducationCourse.status).where(
            EducationCourse.id == enrollment.course_id,
            EducationCourse.tenant_id == tenant_id,
            EducationCourse.workspace_id == workspace_id,
        )
    )
    if course_status != CourseStatus.ACTIVE.value:
        return EducationAccessReason.COURSE_INACTIVE

    batch = await session.scalar(
        select(EducationBatch).where(
            EducationBatch.id == enrollment.batch_id,
            EducationBatch.course_id == enrollment.course_id,
            EducationBatch.tenant_id == tenant_id,
            EducationBatch.workspace_id == workspace_id,
        )
    )
    if batch is None or batch.status != BatchStatus.ACTIVE.value:
        return EducationAccessReason.BATCH_INACTIVE
    if batch.starts_on is not None and as_of < batch.starts_on:
        return EducationAccessReason.BATCH_NOT_STARTED
    if batch.ends_on is not None and as_of > batch.ends_on:
        return EducationAccessReason.BATCH_ENDED

    if enrollment.starts_on is not None and as_of < enrollment.starts_on:
        return EducationAccessReason.ACCESS_NOT_STARTED
    if enrollment.ends_on is not None and as_of > enrollment.ends_on:
        return EducationAccessReason.ACCESS_ENDED
    return None


_STATUS_REASON: dict[str, EducationAccessReason] = {
    EnrollmentStatus.PENDING.value: EducationAccessReason.ENROLLMENT_PENDING,
    EnrollmentStatus.SUSPENDED.value: EducationAccessReason.ENROLLMENT_SUSPENDED,
    EnrollmentStatus.EXPIRED.value: EducationAccessReason.ENROLLMENT_EXPIRED,
    EnrollmentStatus.REVOKED.value: EducationAccessReason.ENROLLMENT_REVOKED,
    EnrollmentStatus.GRADUATED.value: EducationAccessReason.ENROLLMENT_GRADUATED,
}


async def authorize_education_access(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent: Agent,
    identity: EducationIdentityCandidate,
    message: str | None = None,
    as_of: date | None = None,
) -> EducationAccessDecision:
    """Resolve a verified Student and one currently valid Enrollment for an Agent."""

    if agent.tenant_id != tenant_id or agent.workspace_id != workspace_id:
        return _decision(
            authorized=False,
            reason=EducationAccessReason.AGENT_SCOPE_MISMATCH,
            agent=agent,
        )
    if agent.deleted_at is not None or agent.status != AgentStatus.ACTIVE:
        return _decision(
            authorized=False,
            reason=EducationAccessReason.AGENT_INACTIVE,
            agent=agent,
        )

    purpose = await get_agent_purpose(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    if purpose is not AgentPurpose.EDUCATION:
        return _decision(
            authorized=False,
            reason=EducationAccessReason.AGENT_NOT_EDUCATION,
            agent=agent,
        )

    try:
        student_identity = await find_workspace_student_identity(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            identity_type=identity.identity_type,
            identifier=identity.identifier,
            verified_only=True,
        )
    except ValueError:
        return _decision(
            authorized=False,
            reason=EducationAccessReason.IDENTITY_INVALID,
            agent=agent,
        )
    if student_identity is None:
        return _decision(
            authorized=False,
            reason=EducationAccessReason.IDENTITY_NOT_VERIFIED,
            agent=agent,
        )

    enrollments = (
        await session.scalars(
            select(EducationEnrollment)
            .where(
                EducationEnrollment.tenant_id == tenant_id,
                EducationEnrollment.workspace_id == workspace_id,
                EducationEnrollment.student_id == student_identity.student_id,
                EducationEnrollment.agent_id == agent.id,
            )
            .order_by(EducationEnrollment.updated_at.desc(), EducationEnrollment.created_at.desc())
        )
    ).all()
    if not enrollments:
        return _decision(
            authorized=False,
            reason=EducationAccessReason.ENROLLMENT_NOT_FOUND,
            agent=agent,
            identity_id=student_identity.id,
            student_id=student_identity.student_id,
        )

    today = as_of or await workspace_today(session, tenant_id=tenant_id, workspace_id=workspace_id)
    valid: list[EducationEnrollment] = []
    first_denial: tuple[EducationEnrollment, EducationAccessReason] | None = None

    for enrollment in enrollments:
        if enrollment.status != EnrollmentStatus.ACTIVE.value:
            reason = _STATUS_REASON.get(enrollment.status, EducationAccessReason.ENROLLMENT_NOT_FOUND)
        else:
            reason = await _active_enrollment_denial_reason(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                enrollment=enrollment,
                as_of=today,
            )
            if reason is None:
                valid.append(enrollment)
                continue
        if first_denial is None:
            first_denial = (enrollment, reason)

    context = await session.scalar(
        select(EducationTutorContext).where(
            EducationTutorContext.tenant_id == tenant_id,
            EducationTutorContext.workspace_id == workspace_id,
            EducationTutorContext.agent_id == agent.id,
            EducationTutorContext.student_id == student_identity.student_id,
        )
    )
    if context is None:
        context = EducationTutorContext(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_id=agent.id,
            student_id=student_identity.student_id,
        )
        session.add(context)
        await session.flush()

    selected: EducationEnrollment | None = None
    normalized_message = " ".join((message or "").casefold().split())
    ambiguous_course = False

    # A number is meaningful only while a persisted course menu is active.
    if normalized_message.isdigit() and context.pending_enrollment_ids:
        option = int(normalized_message)
        if 1 <= option <= len(context.pending_enrollment_ids):
            selected_id = UUID(context.pending_enrollment_ids[option - 1])
            selected = next((item for item in valid if item.id == selected_id), None)

    courses = (
        await session.scalars(
            select(EducationCourse).where(
                EducationCourse.tenant_id == tenant_id,
                EducationCourse.workspace_id == workspace_id,
                EducationCourse.status == CourseStatus.ACTIVE.value,
            )
        )
    ).all()
    requested_course: EducationCourse | None = None
    if normalized_message and selected is None:
        matches: list[EducationCourse] = []
        for course in courses:
            aliases = {course.code.casefold(), course.name.casefold()}
            aliases.update(str(alias).casefold().strip() for alias in course.aliases)
            for alias in sorted((value for value in aliases if value), key=len, reverse=True):
                match = re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", normalized_message)
                if match is not None and not re.search(r"\bnot\s+$", normalized_message[: match.start()]):
                    matches.append(course)
                    break
        unique_matches = {item.id: item for item in matches}
        if len(unique_matches) == 1:
            requested_course = next(iter(unique_matches.values()))
            matching_enrollments = [item for item in valid if item.course_id == requested_course.id]
            if len(matching_enrollments) > 1:
                # A student may legitimately attend different batches of the
                # same course. Require the numbered course/batch menu instead
                # of denying all their other enrollments.
                ambiguous_course = True
            selected = matching_enrollments[0] if matching_enrollments else None
            if ambiguous_course:
                selected = None
            if not matching_enrollments:
                context.pending_enrollment_ids = []
                return _decision(
                    authorized=False,
                    reason=EducationAccessReason.COURSE_NOT_ENROLLED,
                    agent=agent,
                    identity_id=student_identity.id,
                    student_id=student_identity.student_id,
                )

    if selected is None and len(valid) == 1:
        selected = valid[0]
    force_course_menu = normalized_message in {"courses", "switch course", "switch courses"}
    if selected is None and context.active_enrollment_id is not None and not force_course_menu and not ambiguous_course:
        selected = next((item for item in valid if item.id == context.active_enrollment_id), None)
    if selected is not None:
        if context.active_enrollment_id != selected.id:
            context.active_paper_id = None
        context.active_enrollment_id = selected.id
        context.pending_enrollment_ids = []
        context.interaction_state = "ready_for_question"
        context.selection_revision += 1
        context.selected_at = datetime.now(UTC)
        await session.flush()
        return _decision(
            authorized=True,
            reason=EducationAccessReason.AUTHORIZED,
            agent=agent,
            identity_id=student_identity.id,
            student_id=student_identity.student_id,
            enrollment=selected,
        )

    if len(valid) > 1:
        context.pending_enrollment_ids = [str(item.id) for item in valid]
        context.interaction_state = "awaiting_course_selection"
        if normalized_message not in {"courses", "switch course", "switch courses"}:
            context.pending_question = message
        await session.flush()
        return _decision(
            authorized=False,
            reason=EducationAccessReason.ENROLLMENT_AMBIGUOUS,
            agent=agent,
            identity_id=student_identity.id,
            student_id=student_identity.student_id,
        )
    enrollment, reason = first_denial or (
        enrollments[0],
        EducationAccessReason.ENROLLMENT_NOT_FOUND,
    )
    return _decision(
        authorized=False,
        reason=reason,
        agent=agent,
        identity_id=student_identity.id,
        student_id=student_identity.student_id,
        enrollment=enrollment,
    )


async def authorize_shared_simplified_access(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, gateway_agent: Agent,
    connection_id: UUID, identity: EducationIdentityCandidate, message: str | None = None,
) -> SharedEducationRoute | None:
    """Resolve an opt-in reusable-channel course selection without touching legacy routes."""
    try:
        student_identity = await find_workspace_student_identity(
            session, tenant_id=tenant_id, workspace_id=workspace_id,
            identity_type=identity.identity_type, identifier=identity.identifier, verified_only=True,
        )
    except ValueError:
        return None
    if student_identity is None:
        return None
    courses = (await session.scalars(select(EducationCourse).where(
        EducationCourse.tenant_id == tenant_id, EducationCourse.workspace_id == workspace_id,
        EducationCourse.simplified_workflow.is_(True), EducationCourse.status == CourseStatus.ACTIVE.value,
        EducationCourse.assigned_agent_id.is_not(None),
    ))).all()
    course_by_id = {course.id: course for course in courses if str(connection_id) in (course.allowed_channel_connection_ids or [])}
    if not course_by_id:
        return None
    enrollments = (await session.scalars(select(EducationEnrollment).where(
        EducationEnrollment.tenant_id == tenant_id, EducationEnrollment.workspace_id == workspace_id,
        EducationEnrollment.student_id == student_identity.student_id,
        EducationEnrollment.course_id.in_(course_by_id), EducationEnrollment.status == EnrollmentStatus.ACTIVE.value,
    ))).all()
    today = await workspace_today(session, tenant_id=tenant_id, workspace_id=workspace_id)
    valid = [row for row in enrollments if await _active_enrollment_denial_reason(session, tenant_id=tenant_id, workspace_id=workspace_id, enrollment=row, as_of=today) is None]
    if not valid:
        return None
    context = await session.scalar(select(EducationTutorContext).where(
        EducationTutorContext.tenant_id == tenant_id, EducationTutorContext.workspace_id == workspace_id,
        EducationTutorContext.agent_id == gateway_agent.id, EducationTutorContext.student_id == student_identity.student_id,
    ))
    if context is None:
        context = EducationTutorContext(tenant_id=tenant_id, workspace_id=workspace_id, agent_id=gateway_agent.id, student_id=student_identity.student_id)
        session.add(context)
        await session.flush()
    normalized = " ".join((message or "").casefold().split())
    student = await session.get(EducationStudent, student_identity.student_id)

    async def target_for(enrollment: EducationEnrollment) -> Agent | None:
        return await session.scalar(select(Agent).where(
            Agent.id == course_by_id[enrollment.course_id].assigned_agent_id,
            Agent.tenant_id == tenant_id, Agent.workspace_id == workspace_id,
            Agent.status == AgentStatus.ACTIVE, Agent.deleted_at.is_(None),
        ))

    # A first /start is only a welcome control turn, never a retrieval query.
    if normalized in _CHAT_START_MESSAGES:
        target = await target_for(valid[0])
        if target is not None:
            return SharedEducationRoute(
                _decision(authorized=True, reason=EducationAccessReason.AUTHORIZED,
                          agent=target, identity_id=student_identity.id,
                          student_id=student_identity.student_id, enrollment=valid[0]),
                target,
                f"Welcome, {student.name if student else 'there'}! I am your learning assistant. How may I help you?",
            )

    # Greetings do not clear an existing course choice.  One-course students
    # can continue immediately; multi-course students are shown how to reopen
    # the explicit course menu.
    if normalized in _GREETING_MESSAGES:
        if len(valid) == 1:
            selected = valid[0]
            target = await target_for(selected)
            if target is not None:
                context.active_enrollment_id = selected.id
                context.pending_enrollment_ids = []
                context.interaction_state = "ready_for_question"
                context.selected_at = datetime.now(UTC)
                await session.flush()
                return SharedEducationRoute(
                    _decision(authorized=True, reason=EducationAccessReason.AUTHORIZED,
                              agent=target, identity_id=student_identity.id,
                              student_id=student_identity.student_id, enrollment=selected),
                    target,
                    "Welcome back!",
                )
        target = await target_for(valid[0])
        if target is not None:
            return SharedEducationRoute(
                _decision(authorized=True, reason=EducationAccessReason.AUTHORIZED,
                          agent=target, identity_id=student_identity.id,
                          student_id=student_identity.student_id, enrollment=valid[0]),
                target,
                "Welcome back! To access your course, type switch course.",
            )

    selected: EducationEnrollment | None = None
    selected_from_menu = False
    if normalized.isdigit() and context.pending_enrollment_ids:
        index = int(normalized) - 1
        if 0 <= index < len(context.pending_enrollment_ids):
            selected = next((row for row in valid if str(row.id) == context.pending_enrollment_ids[index]), None)
            selected_from_menu = selected is not None
    if selected is None and context.pending_enrollment_ids and normalized:
        # The menu explicitly permits a course name, so resolve an exact
        # normalized course name/code as well as its displayed number.
        named = [
            row for row in valid
            if " ".join(course_by_id[row.course_id].name.casefold().split()) == normalized
            or " ".join(course_by_id[row.course_id].code.casefold().split()) == normalized
        ]
        if len(named) == 1:
            selected = named[0]
            selected_from_menu = True
    if normalized in _COURSE_MENU_MESSAGES:
        selected = None
        context.active_enrollment_id = None
    if selected is None and context.active_enrollment_id is not None and normalized not in _COURSE_MENU_MESSAGES:
        selected = next((row for row in valid if row.id == context.active_enrollment_id), None)
    if selected is None and len(valid) == 1:
        selected = valid[0]
    if selected is None:
        context.pending_enrollment_ids = [str(row.id) for row in valid]
        context.interaction_state = "awaiting_course_selection"
        context.pending_question = message if normalized not in {"courses", "switch course", "switch courses", "hi", "hello", "hey"} else None
        await session.flush()
        return SharedEducationRoute(_decision(authorized=False, reason=EducationAccessReason.ENROLLMENT_AMBIGUOUS, agent=gateway_agent, identity_id=student_identity.id, student_id=student_identity.student_id), None)
    target = await target_for(selected)
    if target is None:
        return SharedEducationRoute(_decision(authorized=False, reason=EducationAccessReason.AGENT_INACTIVE, agent=gateway_agent, identity_id=student_identity.id, student_id=student_identity.student_id, enrollment=selected), None)
    context.active_enrollment_id = selected.id
    context.pending_enrollment_ids = []
    context.interaction_state = "ready_for_question"
    context.selected_at = datetime.now(UTC)
    await session.flush()
    return SharedEducationRoute(
        _decision(authorized=True, reason=EducationAccessReason.AUTHORIZED, agent=target,
                  identity_id=student_identity.id, student_id=student_identity.student_id,
                  enrollment=selected),
        target,
        "Your course is selected. You can ask questions now." if selected_from_menu else None,
    )


async def education_course_menu(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    student_id: UUID,
) -> str:
    """Render the persisted menu snapshot without rebuilding its option ordering."""
    context = await session.scalar(
        select(EducationTutorContext).where(
            EducationTutorContext.tenant_id == tenant_id,
            EducationTutorContext.workspace_id == workspace_id,
            EducationTutorContext.agent_id == agent_id,
            EducationTutorContext.student_id == student_id,
        )
    )
    if context is None or not context.pending_enrollment_ids:
        return "Your course list changed. Send “courses” to refresh it."
    enrollment_ids = [UUID(value) for value in context.pending_enrollment_ids]
    rows = (
        await session.execute(
            select(EducationEnrollment.id, EducationCourse.name)
            .join(EducationCourse, EducationCourse.id == EducationEnrollment.course_id)
            .where(
                EducationEnrollment.id.in_(enrollment_ids),
                EducationEnrollment.tenant_id == tenant_id,
                EducationEnrollment.workspace_id == workspace_id,
                EducationEnrollment.student_id == student_id,
            )
        )
    ).all()
    names = {enrollment_id: name for enrollment_id, name in rows}
    options = [
        f"{index}. {names[enrollment_id]}"
        for index, enrollment_id in enumerate(enrollment_ids, start=1)
        if enrollment_id in names
    ]
    return (
        "Welcome back. Your active courses are:\n\n"
        + "\n".join(options)
        + "\n\nReply with a number or course name."
    )


async def consume_pending_education_question(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_id: UUID,
    student_id: UUID,
) -> str | None:
    context = await session.scalar(
        select(EducationTutorContext)
        .where(
            EducationTutorContext.tenant_id == tenant_id,
            EducationTutorContext.workspace_id == workspace_id,
            EducationTutorContext.agent_id == agent_id,
            EducationTutorContext.student_id == student_id,
        )
        .with_for_update()
    )
    if context is None or context.pending_question is None:
        return None
    question = context.pending_question.strip()
    context.pending_question = None
    await session.flush()
    return question or None
