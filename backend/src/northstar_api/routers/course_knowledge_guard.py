"""Normal Education uploads must declare their destination before ingestion.

Registered before the legacy Knowledge router. Support/lead-generation behavior
is delegated unchanged; pre-existing unassigned Education files remain inspectable.
"""
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.education import EducationCourse
from northstar_api.education_enrollments import EducationEnrollment
from northstar_api.routers.agents import scoped_agent
from northstar_api.routers.knowledge import DB, KnowledgeManagePrincipal, add_knowledge
from northstar_api.schemas import KnowledgeCreate, KnowledgeOut

router = APIRouter(tags=["course-knowledge"])


@router.post("/agents/{agent_id}/knowledge", response_model=KnowledgeOut, status_code=201)
async def education_upload_guard(agent_id: UUID, payload: KnowledgeCreate, principal: KnowledgeManagePrincipal, session: DB) -> KnowledgeOut:
    if principal.agent_ids is not None and agent_id not in principal.agent_ids:
        raise HTTPException(404, "Agent not found")
    agent = await scoped_agent(session, principal.tenant_id, agent_id, workspace_id=principal.workspace_id)
    is_education = (
        await get_agent_purpose(
            session,
            tenant_id=principal.tenant_id,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
        )
        is AgentPurpose.EDUCATION
    )
    if is_education and payload.education_destination is None and not payload.simplified_training:
        raise HTTPException(409, "Select course and curriculum first: use /agents/{agent_id}/education-knowledge/uploads")
    if is_education and payload.simplified_training:
        legacy_course = await session.scalar(select(EducationCourse.id).where(
            EducationCourse.tenant_id == principal.tenant_id,
            EducationCourse.workspace_id == agent.workspace_id,
            EducationCourse.assigned_agent_id == agent.id,
            EducationCourse.simplified_workflow.is_(False),
        ).limit(1))
        legacy_enrollment = await session.scalar(
            select(EducationEnrollment.id)
            .join(EducationCourse, EducationCourse.id == EducationEnrollment.course_id)
            .where(
                EducationEnrollment.tenant_id == principal.tenant_id,
                EducationEnrollment.workspace_id == agent.workspace_id,
                EducationEnrollment.agent_id == agent.id,
                EducationCourse.simplified_workflow.is_(False),
            )
            .limit(1)
        )
        if legacy_course is not None or legacy_enrollment is not None:
            raise HTTPException(409, "This Education Agent is used by a legacy paper-based Course; use Course Knowledge for its uploads")
    return await add_knowledge(agent_id, payload, principal, session)
