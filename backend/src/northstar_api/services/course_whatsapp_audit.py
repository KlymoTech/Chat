"""Idempotent Education WhatsApp Q&A audit, independent of provider retries."""

from __future__ import annotations

import hashlib

from sqlalchemy import select

from northstar_api.course_knowledge_models import (
    CourseAcademicReview,
    CourseEnrollmentAccess,
    CourseResponseContext,
    CourseWhatsappTurn,
)
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education import EducationCourse
from northstar_api.education_batches import EducationBatch
from northstar_api.education_enrollments import EducationEnrollment
from northstar_api.models import Message, MessageRole


async def sync_course_whatsapp_turn(session, *, agent, receipt, answer_path: str | None = None) -> CourseWhatsappTurn:
    row = await session.scalar(select(CourseWhatsappTurn).where(
        CourseWhatsappTurn.tenant_id == agent.tenant_id,
        CourseWhatsappTurn.workspace_id == agent.workspace_id,
        CourseWhatsappTurn.agent_id == agent.id,
        CourseWhatsappTurn.receipt_id == receipt.id,
    ).with_for_update())
    if row is None:
        row = CourseWhatsappTurn(tenant_id=agent.tenant_id, workspace_id=agent.workspace_id,
            agent_id=agent.id, receipt_id=receipt.id, question=receipt.message_text,
            answer="", answer_path=answer_path or "pending", delivery_status="pending",
            citations=[], provider_message_ids=[])
        session.add(row)
    key = "wa:" + hashlib.sha256(receipt.provider_message_id.encode()).hexdigest()
    question = await session.scalar(select(Message).where(
        Message.tenant_id == receipt.tenant_id, Message.idempotency_key == key,
        Message.role == MessageRole.USER,
    ))
    if question:
        row.question_message_id = question.id
        # Course selection may resume a previously queued question by changing
        # the chat input. Keep the actual inbound text for this provider receipt.
        if not row.question:
            row.question = question.content
        row.conversation_id = question.conversation_id
        answer = await session.scalar(select(Message).where(
            Message.tenant_id == receipt.tenant_id,
            Message.conversation_id == question.conversation_id,
            Message.sequence == question.sequence + 1,
            Message.role == MessageRole.ASSISTANT,
        ))
        if answer:
            row.answer_message_id = answer.id
            row.answer = answer.content
            row.latency_ms = answer.latency_ms
            response = await session.scalar(select(CourseResponseContext).where(
                CourseResponseContext.message_id == answer.id,
                CourseResponseContext.tenant_id == agent.tenant_id,
                CourseResponseContext.workspace_id == agent.workspace_id,
                CourseResponseContext.agent_id == agent.id,
            ))
            if response:
                row.enrollment_id = response.enrollment_id
                row.context_fingerprint = response.context_fingerprint
                row.citations = response.citations
                row.answer_path = response.answer_path
            review = await session.scalar(select(CourseAcademicReview).where(
                CourseAcademicReview.message_id == answer.id,
                CourseAcademicReview.tenant_id == agent.tenant_id,
                CourseAcademicReview.workspace_id == agent.workspace_id,
                CourseAcademicReview.agent_id == agent.id,
            ))
            if review:
                row.review_id = review.id
                row.review_status = review.status
    if row.conversation_id:
        context = await session.scalar(select(EducationConversationContext).where(
            EducationConversationContext.conversation_id == row.conversation_id,
            EducationConversationContext.tenant_id == agent.tenant_id,
            EducationConversationContext.workspace_id == agent.workspace_id,
            EducationConversationContext.agent_id == agent.id,
        ))
        if context:
            row.enrollment_id = context.enrollment_id
            row.course_id = context.course_id
            row.batch_id = context.batch_id
            access = await session.scalar(select(CourseEnrollmentAccess).where(
                CourseEnrollmentAccess.enrollment_id == context.enrollment_id,
                CourseEnrollmentAccess.tenant_id == agent.tenant_id,
                CourseEnrollmentAccess.workspace_id == agent.workspace_id,
                CourseEnrollmentAccess.agent_id == agent.id,
            ))
            if access:
                row.curriculum_id = access.curriculum_id
                row.paper_id = access.selected_paper_id
    if answer_path and row.answer_path == "pending":
        row.answer_path = answer_path
    row.provider_message_ids = list(receipt.outbound_message_ids or [])
    if receipt.status == "processed":
        # A transient worker failure can be retried successfully. A failed
        # delivery callback is different and must remain visible for staff.
        if row.delivery_status not in {"sent", "delivered", "read", "failed"} or (
            row.delivery_status == "failed" and (row.error or "").startswith("processing failed:")
        ):
            row.delivery_status = "submitted"
    elif row.delivery_status not in {"sent", "delivered", "read"}:
        row.delivery_status = receipt.status
    if receipt.last_error:
        row.error = receipt.last_error
    elif receipt.status == "processed" and row.delivery_status != "failed":
        row.error = None
    await session.flush()
    return row
