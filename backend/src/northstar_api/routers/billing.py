from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from northstar_api.dependencies import DBSession, require_permissions
from northstar_api.entitlement_schemas import (
    EntitlementFeaturesOut,
    EntitlementLimitsOut,
    EntitlementUsageOut,
    TenantEntitlementsOut,
)
from northstar_api.models import Tenant
from northstar_api.security import Principal
from northstar_api.services.entitlements import entitlement_context
from northstar_api.services.subscriptions import (
    SubscriptionError,
    cancel_tenant_subscription,
    ensure_tenant_subscription,
    reactivate_tenant_subscription,
)
from northstar_api.subscription_schemas import (
    TenantSubscriptionCancellationRequest,
    TenantSubscriptionOut,
)
from northstar_api.subscriptions import TenantSubscription

router = APIRouter(prefix="/billing", tags=["billing"])
BillingViewPrincipal = Annotated[Principal, Depends(require_permissions("billing.view"))]
BillingManagePrincipal = Annotated[Principal, Depends(require_permissions("billing.manage"))]


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


def _require_interactive_billing_session(principal: Principal) -> None:
    if principal.token_id.startswith("api_key:"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API keys cannot manage tenant billing or offboarding",
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


@router.post("/cancel", response_model=TenantSubscriptionOut)
async def cancel_subscription(
    payload: TenantSubscriptionCancellationRequest,
    principal: BillingManagePrincipal,
    session: DBSession,
) -> TenantSubscriptionOut:
    _require_interactive_billing_session(principal)
    # Pydantic enforces the literal confirmation. Keeping the value in the
    # handler makes the destructive intent explicit at this boundary.
    assert payload.confirmation == "CANCEL"
    try:
        subscription = await cancel_tenant_subscription(
            session,
            tenant_id=principal.tenant_id,
        )
        await session.commit()
        await session.refresh(subscription)
        return _out(subscription)
    except SubscriptionError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.post("/reactivate", response_model=TenantSubscriptionOut)
async def reactivate_subscription(
    principal: BillingManagePrincipal,
    session: DBSession,
) -> TenantSubscriptionOut:
    _require_interactive_billing_session(principal)
    try:
        subscription = await reactivate_tenant_subscription(
            session,
            tenant_id=principal.tenant_id,
        )
        await session.commit()
        await session.refresh(subscription)
        return _out(subscription)
    except SubscriptionError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None


@router.get("/entitlements", response_model=TenantEntitlementsOut)
async def get_entitlements(
    principal: BillingViewPrincipal,
    session: DBSession,
) -> TenantEntitlementsOut:
    context = await entitlement_context(session, tenant_id=principal.tenant_id)
    policy = context.policy
    usage = context.usage
    return TenantEntitlementsOut(
        plan=context.subscription.plan,
        subscription_status=context.subscription.status,
        limits=EntitlementLimitsOut(
            workspaces=policy.workspace_limit,
            agents=policy.agent_limit,
            members=policy.member_limit,
            conversations_monthly=policy.conversation_limit_monthly,
            tokens_monthly=policy.token_limit_monthly,
            storage_bytes=policy.storage_limit_bytes,
        ),
        usage=EntitlementUsageOut(
            workspaces=usage.workspaces,
            agents=usage.agents,
            members=usage.members,
            pending_member_seats=usage.pending_member_seats,
            conversations_monthly=usage.conversations_monthly,
            tokens_monthly=usage.tokens_monthly,
            storage_bytes=usage.storage_bytes,
        ),
        features=EntitlementFeaturesOut(
            allowed_channels=sorted(policy.allowed_channels),
            crm=policy.crm_enabled,
            api=policy.api_enabled,
            white_label=policy.white_label_enabled,
        ),
    )
