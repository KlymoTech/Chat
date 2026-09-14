from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Lead
from northstar_api.schemas import ConversationOut
from northstar_api.security import Principal


async def attach_lead_status(
    session: AsyncSession, principal: Principal, conversations: Sequence[ConversationOut]
) -> None:
    """Load linked lead statuses in one scoped query for either inbox."""
    if not conversations:
        return
    by_id = {item.id: item for item in conversations}
    leads = await session.execute(
        select(Lead.id, Lead.conversation_id, Lead.agent_id, Lead.status).where(
            Lead.tenant_id == principal.tenant_id,
            Lead.workspace_id == principal.workspace_id,
            Lead.conversation_id.in_(by_id),
        )
    )
    for item in conversations:
        item.can_update_lead_status = principal.can("leads.update")
    for lead_id, conversation_id, agent_id, status in leads:
        item = by_id[conversation_id]
        if item.agent_id == agent_id:
            item.lead_id = lead_id
            item.lead_status = status
