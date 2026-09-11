from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.models import Tenant
from northstar_api.schemas import APIModel
from northstar_api.security import Principal
from northstar_api.services.subscriptions import ensure_tenant_subscription
from northstar_api.subscription_schemas import TenantSubscriptionOut
from northstar_api.subscriptions import TenantSubscription

router = APIRouter(prefix="/billing", tags=["billing"])
BillingViewPrincipal = Annotated[Principal, Depends(require_permissions("billing.view"))]


def _out(subscription: TenantSubscription) -> TenantSubscriptionOut:
    return TenantSubscriptionOut(
        id=subscription.id,
        tenant_id=subscription.tenant_id,
        plan=subscription.plan,
        status=subscription.status,
        provider=subscription.provider,
        trial_ends_at=subscription.trial_ends_at,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        past_due_at=subscription.past_due_at,
        suspended_at=subscription.suspended_at,
        cancelled_at=subscription.cancelled_at,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


@router.get("/subscription", response_model=TenantSubscriptionOut)
async def get_subscription(
    principal: BillingViewPrincipal,
    session: DBSession,
) -> TenantSubscriptionOut:
    tenant = await session.scalar(select(Tenant).where(Tenant.id == principal.tenant_id))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    subscription = await ensure_tenant_subscription(session, tenant=tenant)
    await session.commit()
    await session.refresh(subscription)
    return _out(subscription)
