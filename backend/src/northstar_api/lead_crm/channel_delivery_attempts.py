from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.channel_models import ChannelDeliveryAttempt, ChannelOutboundDelivery

ChannelAttemptPhase = Literal["dispatch", "provider"]


def record_channel_delivery_attempt(
    session: AsyncSession,
    delivery: ChannelOutboundDelivery,
    *,
    phase: ChannelAttemptPhase,
    attempt_number: int,
    outcome: str,
    error_code: str | None = None,
) -> ChannelDeliveryAttempt:
    """Append safe normalized evidence for one completed delivery attempt.

    Recipient identities, provider message IDs, message text, raw provider errors,
    payloads and credentials deliberately have no place in this schema.
    """

    attempt = ChannelDeliveryAttempt(
        tenant_id=delivery.tenant_id,
        workspace_id=delivery.workspace_id,
        delivery_id=delivery.id,
        phase=phase,
        attempt_number=attempt_number,
        outcome=outcome[:40],
        error_code=error_code[:120] if error_code else None,
    )
    session.add(attempt)
    return attempt
