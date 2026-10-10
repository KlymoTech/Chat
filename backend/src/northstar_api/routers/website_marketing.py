"""Consent-specific owner controls and public one-click marketing unsubscribe.

Reuses the authoritative Lead / LeadConsent tables and shared audit/outbox.
Never modifies separate processing consent or automatically dispatches messages.
"""
from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from html import escape
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from northstar_api.config import get_settings
from northstar_api.dependencies import DBSession, require_roles
from northstar_api.lead_crm.audit import record_audit_event
from northstar_api.lead_crm.models import LeadConsent
from northstar_api.lead_crm.website_marketing_suppression import (
    InvalidUnsubscribeToken,
    MARKETINGMARKETING_STOP_STATUSES,
    make_unsubscribe_token,
    verify_unsubscribe_token,
)
from northstar_api.models import Lead, Role, Workspace, WorkspaceStatus
from northstar_api.security import Principal
from northstar_api.services.outbox import enqueue_event
from northstar_api.services.rate_limit import redis_services

router = APIRouter(prefix="/site-marketing", tags=["website marketing preferences"])
Owner = Annotated[Principal, Depends(require_roles(Role.OWNER, Role.ADMIN))]


async def _scoped_lead(
    session: DBSession, *, tenant_id: UUID, workspace_id: UUID,
    lead_id: UUID, lock: bool = False,
) -> Lead:
    query = select(Lead).where(
        Lead.id == lead_id, Lead.tenant_id == tenant_id,
        Lead.workspace_id == workspace_id,
    )
    if lock:
        query = query.with_for_update()
    lead = await session.scalar(query)
    if lead is None:
        raise HTTPException(404, "Lead not found")
    return lead


async def _current_marketing_consent(
    session: DBSession, *, tenant_id: UUID, lead_id: UUID,
) -> LeadConsent | None:
    return await session.scalar(
        select(LeadConsent).where(
            LeadConsent.tenant_id == tenant_id,
            LeadConsent.lead_id == lead_id,
            LeadConsent.consent_type == "marketing",
        ).order_by(LeadConsent.created_at.desc(), LeadConsent.id.desc()).limit(1)
    )


async def _withdraw_marketing(
    session: DBSession, *,
    lead: Lead, source: str, actor_user_id: UUID | None,
) -> bool:
    """Only a new marketing withdrawal writes a receipt, audit and outbox event.

    Caller holds the Lead row lock; transactional calls are replay-safe.
    """
    previous = await _current_marketing_consent(
        session, tenant_id=lead.tenant_id, lead_id=lead.id,
    )
    if previous is not None and previous.status.strip().lower() in _STOP_STATUSES:
        return False
    now = datetime.now(UTC)
    receipt = LeadConsent(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        consent_type="marketing",
        status="withdrawn",
        source=source,
        channel="email",
        text_version="marketing-unsubscribe-v1",
        captured_at=now,
        withdrawn_at=now,
        metadata_json={"purpose": "marketing", "method": source},
    )
    session.add(receipt)
    await session.flush()
    record_audit_event(
        session,
        tenant_id=lead.tenant_id, workspace_id=lead.workspace_id,
        actor_user_id=actor_user_id,
        action="website.marketing.consent.withdrawn",
        entity_type="lead",
        entity_id=str(lead.id),
        category="lead",
        before={"marketingConsent": previous.status if previous is not None else "unknown"},
        after={"marketingConsent": "withdrawn", "receiptId": str(receipt.id)},
        metadata={"method": source, "processingConsentUnchanged": True},
    )
    event = enqueue_event(
        session,
        tenant_id=lead.tenant_id,
        aggregate_type="lead",
        aggregate_id=lead.id,
        event_type="lead.marketing.consent.withdrawn.v1",
        payload={
            "leadId": str(lead.id),
            "workspaceId": str(lead.workspace_id),
            "consentType": "marketing",
            "status": "withdrawn",
            "receiptId": str(receipt.id),
        },
    )
    event.workspace_id = lead.workspace_id
    await session.commit()
    return True


def _owner_workspace(principal: Principal) -> UUID:
    if principal.workspace_id is None:
        raise HTTPException(400, "Select a workspace")
    return principal.workspace_id


@router.get("/leads/{lead_id}/preferences")
async def owner_marketing_preferences(
    lead_id: UUID, principal: Owner, session: DBSession, response: Response,
) -> dict[str, str | bool | None]:
    response.headers["Cache-Control"] = "private, no-store"
    lead = await _scoped_lead(
        session, tenant_id=principal.tenant_id,
        workspace_id=_owner_workspace(principal), lead_id=lead_id,
    )
    receipt = await _current_marketing_consent(
        session, tenant_id=lead.tenant_id, lead_id=lead.id,
    )
    status = (
        "withdrawn" if receipt is not None and receipt.withdrawn_at is not None
        else receipt.status.strip().casefold() if receipt is not None else "unknown"
    )
    return {
        "leadId": str(lead.id), "marketingStatus": status,
        "marketingAllowed": status == "granted",
        "processingConsentPreserved": True,
        "note": "Marketing permission is separate from enquiry-processing consent.",
    }


@router.post("/leads/{lead_id}/unsubscribe-link")
async def owner_unsubscribe_link(
    lead_id: UUID, principal: Owner, session: DBSession, response: Response,
) -> dict[str, str]:
    response.headers["Cache-Control"] = "private, no-store"
    lead = await _scoped_lead(
        session, tenant_id=principal.tenant_id,
        workspace_id=_owner_workspace(principal), lead_id=lead_id,
    )
    token = make_unsubscribe_token(
        tenant_id=lead.tenant_id, workspace_id=lead.workspace_id,
        lead_id=lead.id, secret=get_settings().jwt_secret.get_secret_value(),
    )
    return {
        "path": "/api/v1/site-marketing/unsubscribe/" + token,
        "expiresIn": "30 days",
        "note": "Signed bearer link. Do not log or share beyond its intended recipient.",
    }


@router.post("/leads/{lead_id}/withdraw")
async def owner_withdraw_marketing(
    lead_id: UUID, principal: Owner, session: DBSession, response: Response,
) -> dict[str, str | bool]:
    response.headers["Cache-Control"] = "private, no-store"
    lead = await _scoped_lead(
        session, tenant_id=principal.tenant_id,
        workspace_id=_owner_workspace(principal), lead_id=lead_id, lock=True,
    )
    changed = await _withdraw_marketing(
        session, lead=lead, source="owner_request", actor_user_id=principal.user_id,
    )
    return {"status": "withdrawn", "changed": changed, "processingConsentPreserved": True}


def _target(token: str) -> tuple[UUID, UUID, UUID]:
    try:
        target = verify_unsubscribe_token(
            token, secret=get_settings().jwt_secret.get_secret_value(),
        )
    except InvalidUnsubscribeToken:
        raise HTTPException(400, "Unsubscribe link is invalid or expired") from None
    return target.tenant_id, target.workspace_id, target.lead_id


_UNSUBSCRIBE_STYLE = (
    "body{font:16px/1.6 system-ui,sans-serif;background:#f8fafc;color:#0f172a;padding:32px}"
    "main{max-width:640px;margin:auto;padding:30px;background:#fff;border:1px solid #cbd5e1;border-radius:12px}"
    "button{padding:12px 22px;border:0;border-radius:7px;background:#1d4ed8;color:white;font:inherit}"
    "button:focus-visible{outline:3px solid #eab308;outline-offset:2px}"
)
_STYLE_SHA = base64.b64encode(hashlib.sha256(_UNSUBSCRIBE_STYLE.encode()).digest()).decode()


def _confirmation(content: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<meta name=\"robots\" content=\"noindex,nofollow\"><title>Marketing preferences</title>"
        f"<style>{_UNSUBSCRIBE_STYLE}</style></head><body><main>{content}</main></body></html>",
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'sha256-" + _STYLE_SHA +
                "'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
            ),
        },
    )


@router.get("/unsubscribe/{token}", include_in_schema=False)
async def unsubscribe_confirmation(token: str) -> HTMLResponse:
    _target(token)  # Read-only. Automated email link previews must not unsubscribe.
    path = "/api/v1/site-marketing/unsubscribe/" + escape(token, quote=True)
    return _confirmation(
        "<h1>Stop marketing messages</h1>"
        "<p>Confirm to stop future marketing messages from this organization. "
        "Your existing enquiry and transactional service communications remain separate.</p>"
        f'<form action="{path}" method="post">'
        '<button type="submit">Unsubscribe from marketing</button></form>'
    )


@router.post("/unsubscribe/{token}", response_model=None)
async def one_click_unsubscribe(
    token: str, request: Request, session: DBSession,
) -> HTMLResponse:
    # RFC 8058 mail clients may submit cross-origin. The signed, expiring
    # purpose-scoped token provides the authorization, not a session cookie.
    tenant_id, workspace_id, lead_id = _target(token)
    limiter = await redis_services.check_rate_limit(
        "marketing-unsubscribe:" + hashlib.sha256(token.encode("ascii")).hexdigest(),
        limit=30, window_seconds=3600, scope="marketing_unsubscribe",
    )
    if not limiter.allowed:
        raise HTTPException(429, "Please retry later", headers={"Retry-After": str(limiter.retry_after)})
    active = await session.scalar(select(Workspace.id).where(
        Workspace.id == workspace_id, Workspace.tenant_id == tenant_id,
        Workspace.status == WorkspaceStatus.ACTIVE,
    ))
    if active is None:
        raise HTTPException(404, "Preference record unavailable")
    lead = await _scoped_lead(
        session, tenant_id=tenant_id, workspace_id=workspace_id,
        lead_id=lead_id, lock=True,
    )
    await _withdraw_marketing(
        session, lead=lead, source="signed_unsubscribe_link", actor_user_id=None,
    )
    return _confirmation(
        "<h1>You are unsubscribed</h1>"
        "<p>Your marketing preferences have been updated. "
        "We may still contact you about an existing enquiry or required service information.</p>"
    )
