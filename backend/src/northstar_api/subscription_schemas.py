from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from northstar_api.schemas import APIModel
from northstar_api.subscriptions import SubscriptionStatus


class TenantSubscriptionOut(APIModel):
    id: UUID
    tenant_id: UUID
    plan: str
    status: SubscriptionStatus
    provider: str | None = None
    trial_ends_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool
    past_due_at: datetime | None = None
    suspended_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TenantSubscriptionCancellationRequest(APIModel):
    confirmation: Literal["CANCEL"]
