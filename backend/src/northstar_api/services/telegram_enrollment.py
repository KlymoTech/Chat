"""Authorize normal Telegram bots using staff-managed Telegram user IDs."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.education_student_identities import EducationStudentIdentity, StudentIdentityType
from northstar_api.education_students import EducationStudent
from northstar_api.lead_crm.channels import CanonicalInboundEvent
from northstar_api.models import Agent
from northstar_api.services.student_identity import normalize_student_identity

DENIED = "This Telegram account is not enrolled for this bot. Ask your school administrator to add your numeric Telegram user ID to your student record."


async def telegram_enrollment_notice(session: AsyncSession, *, event: CanonicalInboundEvent, agent: Agent) -> tuple[str, dict[str, Any]] | None:
    """Stop unknown Telegram identities before they enter the chat pipeline."""
    if event.metadata.get("chatType") != "private" or event.conversation_reference != event.sender.external_id:
        return None
    try:
        sender = normalize_student_identity(StudentIdentityType.TELEGRAM, event.sender.external_id or "")
    except ValueError:
        return None
    identity = await session.scalar(select(EducationStudentIdentity).where(EducationStudentIdentity.tenant_id == agent.tenant_id, EducationStudentIdentity.workspace_id == agent.workspace_id, EducationStudentIdentity.identity_type == "telegram", EducationStudentIdentity.normalized_identifier == sender))
    if identity is None or identity.status != "verified":
        return DENIED, {}
    student = await session.scalar(select(EducationStudent).where(
        EducationStudent.id == identity.student_id,
        EducationStudent.tenant_id == agent.tenant_id,
        EducationStudent.workspace_id == agent.workspace_id,
        EducationStudent.status == "active",
    ))
    return None if student is not None else (DENIED, {})
