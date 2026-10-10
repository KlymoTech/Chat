"""Purpose-limited marketing email consent; never infer consent from contact forms."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.config import get_settings
from northstar_api.lead_crm.models import LeadConsent
from northstar_api.models import Lead

UNSUBSCRIBE_TOKEN_TTL_SECONDS = 365 * 24 * 3600
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,256}\.[a-f0-9]{64}$")
_DOMAIN = b"northstar.website.marketing.unsubscribe.v1"


@dataclass(frozen=True)
class EmailMarketingPermission:
    allowed: bool
    reason: str


def _key() -> bytes:
    secret = get_settings().jwt_secret.get_secret_value().encode("utf-8")
    return hmac.new(secret, _DOMAIN, hashlib.sha256).digest()


def sign_unsubscribe_token(workspace_id: UUID, lead_id: UUID, *, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else int(now)
    data = f"{workspace_id}:{lead_id}:{issued}".encode("ascii")
    payload = base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
    signature = hmac.new(_key(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return payload + "." + signature


def verify_unsubscribe_token(token: str, *, now: int | None = None) -> tuple[UUID, UUID] | None:
    if not _TOKEN.fullmatch(token):
        return None
    payload, signature = token.rsplit(".", 1)
    expected = hmac.new(_key(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        workspace, lead, timestamp = raw.decode("ascii").split(":")
        issued = int(timestamp)
        current = int(time.time()) if now is None else int(now)
        if issued > current + 300 or current - issued > UNSUBSCRIBE_TOKEN_TTL_SECONDS:
            return None
        return UUID(workspace), UUID(lead)
    except (ValueError, UnicodeError, binascii.Error):
        return None


def _email(value: str | None) -> str | None:
    return value.strip().casefold() if value and value.strip() else None


async def matched_email_lead_ids(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, email: str | None,
) -> list[UUID]:
    normalized = _email(email)
    if normalized is None:
        return []
    rows = await session.scalars(select(Lead.id).where(
        Lead.tenant_id == tenant_id,
        Lead.workspace_id == workspace_id,
        func.lower(func.trim(Lead.email)) == normalized,
    ).order_by(Lead.id))
    return list(rows.all())


async def email_marketing_permission(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, lead: Lead,
) -> EmailMarketingPermission:
    """A separate explicit marketing-email consent must exist for this Lead.

    A withdrawal by any same-workspace Lead with the same normalized email is
    a suppression for all duplicates, including Leads created after opt-out.
    """
    if lead.tenant_id != tenant_id or lead.workspace_id != workspace_id:
        return EmailMarketingPermission(False, "scope_mismatch")
    if not lead.email:
        return EmailMarketingPermission(False, "missing_email")
    if not lead.consent or lead.status == "archived":
        return EmailMarketingPermission(False, "processing_not_allowed")
    related = await matched_email_lead_ids(
        session, tenant_id=tenant_id, workspace_id=workspace_id, email=lead.email,
    )
    if lead.id not in related:
        return EmailMarketingPermission(False, "lead_not_found")
    records = (await session.scalars(select(LeadConsent).where(
        LeadConsent.tenant_id == tenant_id,
        LeadConsent.lead_id.in_(related),
        LeadConsent.consent_type == "marketing_email",
    ).order_by(LeadConsent.captured_at.desc(), LeadConsent.id.desc()))).all()
    if any(record.status.lower() in {"withdrawn", "revoked", "denied", "opted_out"}
           for record in records):
        return EmailMarketingPermission(False, "suppressed")
    own = [record for record in records if record.lead_id == lead.id]
    if not own or own[0].status.lower() != "granted":
        return EmailMarketingPermission(False, "missing_marketing_consent")
    return EmailMarketingPermission(True, "explicit_marketing_email_consent")
