from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.agent_purpose import AgentPurpose, get_agent_purpose
from northstar_api.education_conversation_context import EducationConversationContext
from northstar_api.education_student_activity import EducationStudentActivityEvent
from northstar_api.lead_crm.domain import LeadLifecycleStatus
from northstar_api.lead_crm.models import LeadActivityEvent
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.logging import request_id_ctx
from northstar_api.models import Channel, Conversation, ConversationState, Lead
from northstar_api.services.outbox import enqueue_event


@dataclass(frozen=True)
class ConversationResolutionResult:
    purpose: AgentPurpose
    lead: Lead | None = None
    lead_created: bool = False
    education_activity_created: bool = False


class ConversationResolutionService:
    """Resolve a conversation according to the Agent's first-class purpose.

    Lead Generation retains the existing idempotent Lead + CRM workflow.
    Education and Support resolve the Conversation without creating a new Lead by
    default. Education additionally records durable Student activity when an
    authorization context is attached to the Conversation.

    The Conversation and its messages always remain the source of truth.
    """

    async def resolve(
        self,
        session: AsyncSession,
        *,
        conversation: Conversation,
        actor_user_id: UUID | None = None,
    ) -> ConversationResolutionResult:
        purpose = await get_agent_purpose(
            session,
            tenant_id=conversation.tenant_id,
            workspace_id=conversation.workspace_id,
            agent_id=conversation.agent_id,
        )
        now = datetime.now(UTC)
        previous_state = conversation.state
        was_resolved = previous_state == ConversationState.RESOLVED

        conversation.state = ConversationState.RESOLVED
        conversation.ended_at = conversation.ended_at or now
        conversation.unread_count = 0

        if purpose is AgentPurpose.LEAD_GENERATION:
            lead, lead_created = await self._finalize_lead(
                session,
                conversation=conversation,
                actor_user_id=actor_user_id,
                now=now,
            )
            if not was_resolved or lead_created:
                self._enqueue_conversation_events(
                    session,
                    conversation=conversation,
                    previous_state=previous_state,
                    purpose=purpose,
                    lead=lead,
                    reconciled=was_resolved and lead_created,
                )
            await session.flush()
            return ConversationResolutionResult(
                purpose=purpose,
                lead=lead,
                lead_created=lead_created,
            )

        education_activity_created = False
        if purpose is AgentPurpose.EDUCATION:
            education_activity_created = await self._record_education_resolution(
                session,
                conversation=conversation,
                actor_user_id=actor_user_id,
            )

        if not was_resolved or education_activity_created:
            self._enqueue_conversation_events(
                session,
                conversation=conversation,
                previous_state=previous_state,
                purpose=purpose,
                lead=None,
                reconciled=was_resolved and education_activity_created,
            )

        await session.flush()
        return ConversationResolutionResult(
            purpose=purpose,
            education_activity_created=education_activity_created,
        )

    async def _finalize_lead(
        self,
        session: AsyncSession,
        *,
        conversation: Conversation,
        actor_user_id: UUID | None,
        now: datetime,
    ) -> tuple[Lead, bool]:
        """Preserve the existing Lead Generation resolution behavior exactly."""

        lead = await session.scalar(
            select(Lead)
            .where(
                Lead.tenant_id == conversation.tenant_id,
                Lead.workspace_id == conversation.workspace_id,
                Lead.conversation_id == conversation.id,
            )
            .with_for_update()
        )
        lead_created = lead is None

        source_fields = {
            "sourceChannel": conversation.channel.value,
            "conversationPublicId": conversation.public_id,
            "conversationResolution": conversation.resolution,
            "resolvedAt": conversation.ended_at.isoformat() if conversation.ended_at else now.isoformat(),
        }

        if lead is None:
            visitor_name = conversation.visitor_name.strip() if conversation.visitor_name else ""
            lead = Lead(
                tenant_id=conversation.tenant_id,
                workspace_id=conversation.workspace_id,
                agent_id=conversation.agent_id,
                conversation_id=conversation.id,
                name=visitor_name if visitor_name and visitor_name != "Anonymous visitor" else None,
                email=conversation.visitor_email,
                phone=(conversation.visitor_id if conversation.channel == Channel.WHATSAPP else None),
                status=LeadLifecycleStatus.NEW.value,
                consent=False,
                fields_json=source_fields,
            )
            session.add(lead)
            await session.flush()
        else:
            if not lead.name and conversation.visitor_name != "Anonymous visitor":
                lead.name = conversation.visitor_name
            if not lead.email and conversation.visitor_email:
                lead.email = conversation.visitor_email
            if not lead.phone and conversation.channel == Channel.WHATSAPP:
                lead.phone = conversation.visitor_id
            lead.fields_json = {**(lead.fields_json or {}), **source_fields}

        await lead_domain_service.ensure_profile(
            session,
            lead=lead,
            source_channel=conversation.channel.value,
            source_provider=conversation.channel.value,
            source_external_id=conversation.visitor_id,
        )

        if lead_created:
            session.add(
                LeadActivityEvent(
                    tenant_id=conversation.tenant_id,
                    lead_id=lead.id,
                    event_type="lead.created.from_conversation.v1",
                    actor_type="user" if actor_user_id else "system",
                    actor_id=str(actor_user_id) if actor_user_id else None,
                    correlation_id=request_id_ctx.get(),
                    details_json={
                        "workspaceId": str(conversation.workspace_id),
                        "agentId": str(conversation.agent_id),
                        "conversationId": str(conversation.id),
                        "channel": conversation.channel.value,
                    },
                )
            )
            lead_payload = {
                "leadId": str(lead.id),
                "workspaceId": str(conversation.workspace_id),
                "agentId": str(conversation.agent_id),
                "conversationId": str(conversation.id),
                "sourceChannel": conversation.channel.value,
            }
            enqueue_event(
                session,
                tenant_id=conversation.tenant_id,
                aggregate_type="lead",
                aggregate_id=lead.id,
                event_type="lead.captured.v1",
                payload=lead_payload,
            )
            enqueue_event(
                session,
                tenant_id=conversation.tenant_id,
                aggregate_type="lead",
                aggregate_id=lead.id,
                event_type="lead.created.v1",
                payload=lead_payload,
            )
            enqueue_event(
                session,
                tenant_id=conversation.tenant_id,
                aggregate_type="lead",
                aggregate_id=lead.id,
                event_type="lead.crm.sync.requested.v1",
                payload={**lead_payload, "reason": "conversation_resolved"},
            )

        return lead, lead_created

    async def _record_education_resolution(
        self,
        session: AsyncSession,
        *,
        conversation: Conversation,
        actor_user_id: UUID | None,
    ) -> bool:
        context = await session.scalar(
            select(EducationConversationContext).where(
                EducationConversationContext.tenant_id == conversation.tenant_id,
                EducationConversationContext.workspace_id == conversation.workspace_id,
                EducationConversationContext.agent_id == conversation.agent_id,
                EducationConversationContext.conversation_id == conversation.id,
            )
        )
        if context is None:
            enqueue_event(
                session,
                tenant_id=conversation.tenant_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="education.conversation.resolution.context_missing.v1",
                payload={
                    "conversationId": str(conversation.id),
                    "workspaceId": str(conversation.workspace_id),
                    "agentId": str(conversation.agent_id),
                },
            )
            return False

        event_type = "conversation.resolved"
        activity = await session.scalar(
            select(EducationStudentActivityEvent)
            .where(
                EducationStudentActivityEvent.tenant_id == conversation.tenant_id,
                EducationStudentActivityEvent.workspace_id == conversation.workspace_id,
                EducationStudentActivityEvent.conversation_id == conversation.id,
                EducationStudentActivityEvent.event_type == event_type,
            )
            .with_for_update()
        )
        created = activity is None
        details = {
            "channel": conversation.channel.value,
            "conversationPublicId": conversation.public_id,
            "resolution": conversation.resolution,
            "resolvedAt": conversation.ended_at.isoformat() if conversation.ended_at else None,
        }
        if activity is None:
            activity = EducationStudentActivityEvent(
                tenant_id=conversation.tenant_id,
                workspace_id=conversation.workspace_id,
                student_id=context.student_id,
                enrollment_id=context.enrollment_id,
                course_id=context.course_id,
                batch_id=context.batch_id,
                agent_id=context.agent_id,
                conversation_id=conversation.id,
                event_type=event_type,
                resolution=conversation.resolution,
                actor_user_id=actor_user_id,
                details_json=details,
            )
            session.add(activity)
            await session.flush()
        else:
            activity.resolution = conversation.resolution
            activity.actor_user_id = actor_user_id or activity.actor_user_id
            activity.details_json = details

        if created:
            payload = {
                "activityId": str(activity.id),
                "conversationId": str(conversation.id),
                "workspaceId": str(conversation.workspace_id),
                "agentId": str(context.agent_id),
                "studentId": str(context.student_id),
                "enrollmentId": str(context.enrollment_id),
                "courseId": str(context.course_id),
                "batchId": str(context.batch_id),
                "eventType": event_type,
            }
            enqueue_event(
                session,
                tenant_id=conversation.tenant_id,
                aggregate_type="education_student",
                aggregate_id=context.student_id,
                event_type="education.student.activity.recorded.v1",
                payload=payload,
            )
            enqueue_event(
                session,
                tenant_id=conversation.tenant_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="education.conversation.resolved.v1",
                payload=payload,
            )
        return created

    @staticmethod
    def _enqueue_conversation_events(
        session: AsyncSession,
        *,
        conversation: Conversation,
        previous_state: ConversationState,
        purpose: AgentPurpose,
        lead: Lead | None,
        reconciled: bool,
    ) -> None:
        conversation_payload = {
            "conversationId": str(conversation.id),
            "workspaceId": str(conversation.workspace_id),
            "agentId": str(conversation.agent_id),
            "leadId": str(lead.id) if lead is not None else None,
            "channel": conversation.channel.value,
            "purpose": purpose.value,
            "reconciled": reconciled,
        }
        enqueue_event(
            session,
            tenant_id=conversation.tenant_id,
            aggregate_type="conversation",
            aggregate_id=conversation.id,
            event_type="conversation.resolved.v1",
            payload=conversation_payload,
        )
        if previous_state != ConversationState.RESOLVED:
            enqueue_event(
                session,
                tenant_id=conversation.tenant_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="conversation.state.changed.v1",
                payload={
                    **conversation_payload,
                    "previousState": previous_state.value,
                    "state": ConversationState.RESOLVED.value,
                },
            )


conversation_resolution_service = ConversationResolutionService()
