from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.models import Tenant
from northstar_api.subscriptions import SubscriptionStatus, TenantSubscription


class SubscriptionError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_plan(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    if not normalized or len(normalized) > 40:
        raise SubscriptionError("Invalid subscription plan")
    return normalized


async def ensure_tenant_subscription(
    session: AsyncSession,
    *,
    tenant: Tenant,
) -> TenantSubscription:
    subscription = await session.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_id == tenant.id)
    )
    if subscription is not None:
        return subscription

    subscription = TenantSubscription(
        tenant_id=tenant.id,
        plan=normalize_plan(tenant.plan or "starter"),
        status=SubscriptionStatus.ACTIVE,
    )
    session.add(subscription)
    await session.flush()
    return subscription


async def create_subscription_for_tenant(
    session: AsyncSession,
    *,
    tenant: Tenant,
    plan: str | None = None,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> TenantSubscription:
    existing = await session.scalar(
        select(TenantSubscription).where(TenantSubscription.tenant_id == tenant.id)
    )
    if existing is not None:
        return existing
    normalized_plan = normalize_plan(plan or tenant.plan or "starter")
    tenant.plan = normalized_plan
    subscription = TenantSubscription(
        tenant_id=tenant.id,
        plan=normalized_plan,
        status=status,
    )
    session.add(subscription)
    await session.flush()
    return subscription


async def set_subscription_state(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    plan: str | None = None,
    status: SubscriptionStatus | None = None,
    provider: str | None = None,
    provider_customer_id: str | None = None,
    provider_subscription_id: str | None = None,
    trial_ends_at: datetime | None = None,
    current_period_start: datetime | None = None,
    current_period_end: datetime | None = None,
    cancel_at_period_end: bool | None = None,
) -> TenantSubscription:
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise SubscriptionError("Tenant not found", 404)
    subscription = await ensure_tenant_subscription(session, tenant=tenant)
    now = datetime.now(UTC)

    if plan is not None:
        normalized_plan = normalize_plan(plan)
        subscription.plan = normalized_plan
        tenant.plan = normalized_plan
    if provider is not None:
        subscription.provider = provider.strip().lower() or None
    if provider_customer_id is not None:
        subscription.provider_customer_id = provider_customer_id.strip() or None
    if provider_subscription_id is not None:
        subscription.provider_subscription_id = provider_subscription_id.strip() or None
    if trial_ends_at is not None:
        subscription.trial_ends_at = trial_ends_at
    if current_period_start is not None:
        subscription.current_period_start = current_period_start
    if current_period_end is not None:
        subscription.current_period_end = current_period_end
    if cancel_at_period_end is not None:
        subscription.cancel_at_period_end = cancel_at_period_end

    if status is not None and status != subscription.status:
        subscription.status = status
        if status == SubscriptionStatus.PAST_DUE:
            subscription.past_due_at = subscription.past_due_at or now
        elif status == SubscriptionStatus.SUSPENDED:
            subscription.suspended_at = subscription.suspended_at or now
        elif status == SubscriptionStatus.CANCELLED:
            subscription.cancelled_at = subscription.cancelled_at or now
        elif status in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL}:
            subscription.past_due_at = None
            subscription.suspended_at = None
            subscription.cancelled_at = None

    await session.flush()
    return subscription
