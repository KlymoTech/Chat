from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.domain import LeadLifecycleStatus
from northstar_api.lead_crm.models import LeadActivityEvent
from northstar_api.lead_crm.services import lead_domain_service
from northstar_api.logging import request_id_ctx
from northstar_api.models import Channel, Conversation, ConversationState, Lead
from northstar_api.services.outbox import enqueue_event


@dataclass(frozen=True)
class ConversationResolutionResult:
    lead: Lead
    lead_created: bool


class ConversationResolutionService:
    """Resolve a conversation and finalize its local lead in one DB transaction.

    This service intentionally never deletes or moves the conversation. The Lead
    keeps a permanent foreign-key reference to the original conversation so the
    complete message history remains the source of truth.
    """

    async def resolve(
        self,
        session: AsyncSession,
        *,
        conversation: Conversation,
        actor_user_id: UUID | None = None,
    ) -> ConversationResolutionResult:
        now = datetime.now(UTC)
        was_resolved = conversation.state == ConversationState.RESOLVED

        conversation.state = ConversationState.RESOLVED
        conversation.ended_at = conversation.ended_at or now
        conversation.unread_count = 0

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
            # A legacy/manual lead can already be linked to the conversation. Fill
            # only missing standard fields and retain every custom field it owns.
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

        if not was_resolved or lead_created:
            conversation_payload = {
                "conversationId": str(conversation.id),
                "workspaceId": str(conversation.workspace_id),
                "agentId": str(conversation.agent_id),
                "leadId": str(lead.id),
                "channel": conversation.channel.value,
                "reconciledLead": was_resolved and lead_created,
            }
            enqueue_event(
                session,
                tenant_id=conversation.tenant_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="conversation.resolved.v1",
                payload=conversation_payload,
            )
            if not was_resolved:
                enqueue_event(
                    session,
                    tenant_id=conversation.tenant_id,
                    aggregate_type="conversation",
                    aggregate_id=conversation.id,
                    event_type="conversation.state.changed.v1",
                    payload={
                        **conversation_payload,
                        "previousState": "open",
                        "state": ConversationState.RESOLVED.value,
                    },
                )

        await session.flush()
        return ConversationResolutionResult(lead=lead, lead_created=lead_created)


conversation_resolution_service = ConversationResolutionService()
