"""First-party, cookie-scoped website consent preference API.

Only explicit choices are stored. No trackers are loaded by this API.
The caller must enforce decisions before collecting/sending optional events.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from northstar_api.config import get_settings
from northstar_api.dependencies import DBSession
from northstar_api.models import Workspace, WorkspaceStatus
from northstar_api.services.rate_limit import redis_services
from northstar_api.services.website_consent_policy import (
    ConsentPreferences, ConsentPurpose, ConsentReceipt, decide_consent,
)
from northstar_api.website_consent_models import WebsiteConsentReceipt

router = APIRouter(prefix="/site-consent", tags=["site-consent"])
POLICY_VERSION = "site-policy-2026-10-v1"
MAX_AGE_DAYS = 180
_TOKEN_FORMAT = re.compile(r"^[0-9a-f]{64}$")


class ConsentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analytics: bool = False
    marketing: bool = False
    personalization: bool = False


def _cookie_name(workspace_id: UUID) -> str:
    return "wsc_" + workspace_id.hex


def _subject_hash(workspace_id: UUID, cookie: str | None) -> str | None:
    if cookie is None or not _TOKEN_FORMAT.fullmatch(cookie):
        return None
    return hashlib.sha256((str(workspace_id) + ":" + cookie).encode("ascii")).hexdigest()


def _global_privacy_control(request: Request) -> bool:
    return request.headers.get("Sec-GPC", "") == "1" or request.headers.get("GPC", "") == "1"


def _same_origin(request: Request) -> None:
    # JSON and same-origin requirements prevent cross-site forms from granting consent.
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site consent updates are not allowed")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != request.headers.get("host", "").lower():
            raise HTTPException(403, "Consent changes must originate on this site")


async def _workspace(session: DBSession, workspace_id: UUID) -> Workspace:
    workspace = await session.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.status == WorkspaceStatus.ACTIVE)
    )
    if workspace is None:
        raise HTTPException(404, "Website workspace not available")
    return workspace


async def _latest(
    session: DBSession, workspace: Workspace, visitor_hash: str | None,
) -> WebsiteConsentReceipt | None:
    if visitor_hash is None:
        return None
    return await session.scalar(
        select(WebsiteConsentReceipt)
        .where(
            WebsiteConsentReceipt.tenant_id == workspace.tenant_id,
            WebsiteConsentReceipt.workspace_id == workspace.id,
            WebsiteConsentReceipt.visitor_hash == visitor_hash,
        )
        .order_by(WebsiteConsentReceipt.created_at.desc(), WebsiteConsentReceipt.id.desc())
        .limit(1)
    )


def _effective(record: WebsiteConsentReceipt | None, *, gpc: bool) -> dict[str, object]:
    when = None
    receipt = None
    if record is not None:
        when = record.created_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        receipt = ConsentReceipt(
            receipt_id=str(record.id), subject_id=record.visitor_hash,
            captured_at=when, source="preferences",
            preferences=ConsentPreferences(
                policy_version=record.policy_version,
                analytics=record.analytics, marketing=record.marketing,
                personalization=record.personalization,
            ),
        )
    decisions = {}
    for purpose in (
        ConsentPurpose.ANALYTICS, ConsentPurpose.MARKETING, ConsentPurpose.PERSONALIZATION,
    ):
        result = decide_consent(
            purpose, receipt, policy_version=POLICY_VERSION,
            at=datetime.now(UTC), max_age_days=MAX_AGE_DAYS,
        )
        allowed = result.allowed
        reason = result.reason
        if gpc and purpose in {ConsentPurpose.MARKETING, ConsentPurpose.PERSONALIZATION}:
            allowed = False
            reason = "browser_opt_out"
        decisions[purpose.value] = {"allowed": allowed, "reason": reason}
    return {
        "policyVersion": POLICY_VERSION,
        "necessary": True,
        "analytics": decisions["analytics"]["allowed"],
        "marketing": decisions["marketing"]["allowed"],
        "personalization": decisions["personalization"]["allowed"],
        "decisions": decisions,
        "globalPrivacyControl": gpc,
        "lastUpdated": when.isoformat() if when is not None else None,
    }


def _private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie, Sec-GPC, GPC"
    response.headers["X-Content-Type-Options"] = "nosniff"


@router.get("/{workspace_id}")
async def read_choices(
    workspace_id: UUID, request: Request, response: Response, session: DBSession,
) -> dict[str, object]:
    """Unknown visitors always begin with all optional purposes disabled."""
    workspace = await _workspace(session, workspace_id)
    subject = _subject_hash(workspace_id, request.cookies.get(_cookie_name(workspace_id)))
    receipt = await _latest(session, workspace, subject)
    _private_response(response)
    return _effective(receipt, gpc=_global_privacy_control(request))


@router.post("/{workspace_id}")
async def save_choices(
    workspace_id: UUID, choices: ConsentSelection, request: Request,
    response: Response, session: DBSession,
) -> dict[str, object]:
    """Append an attributable-to-browser preference receipt; never infer consent."""
    _same_origin(request)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "Use JSON for consent updates")
    workspace = await _workspace(session, workspace_id)
    # Rate-limit unauthenticated writes without storing raw client IPs in Redis.
    address = request.client.host if request.client else "unknown"
    digest = hmac.new(
        get_settings().jwt_secret.get_secret_value().encode("utf-8"),
        f"{workspace_id}:{address}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]
    rate = await redis_services.check_rate_limit(
        f"site-consent:{workspace_id}:{digest}", 30,
        window_seconds=3600, scope="site_consent",
    )
    if not rate.allowed:
        raise HTTPException(
            429, "Too many consent updates", headers={"Retry-After": str(rate.retry_after)},
        )
    name = _cookie_name(workspace_id)
    token = request.cookies.get(name)
    subject = _subject_hash(workspace_id, token)
    if subject is None:
        token = secrets.token_hex(32)
        subject = _subject_hash(workspace_id, token)
    assert subject is not None
    gpc = _global_privacy_control(request)
    record = WebsiteConsentReceipt(
        tenant_id=workspace.tenant_id, workspace_id=workspace.id,
        visitor_hash=subject, policy_version=POLICY_VERSION,
        analytics=choices.analytics,
        marketing=choices.marketing and not gpc,
        personalization=choices.personalization and not gpc,
        gpc_override=gpc, source="preferences", created_at=datetime.now(UTC),
    )
    session.add(record)
    await session.commit()
    _private_response(response)
    response.set_cookie(
        key=name, value=token, max_age=MAX_AGE_DAYS * 86400,
        httponly=True, secure=get_settings().is_production,
        samesite="lax",
        path=get_settings().app_api_prefix.rstrip("/") + "/site-consent",
    )
    return _effective(record, gpc=gpc)
