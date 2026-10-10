"""Purpose-scoped signed unsubscribe links using the existing LeadConsent ledger.

The token contains opaque UUIDs only, expires, and is cryptographically separate
from login/session tokens. GET links never change permissions (mail link scanners).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.models import LeadConsent
from northstar_api.models import Lead

# Shared by preference APIs, form opt-in and any future provider send gate.
# A new form must not silently reverse a prior explicit withdrawal.
MARKETING_STOP_STATUSES = frozenset({"withdrawn", "revoked", "denied", "opted_out"})

_TOKEN_PURPOSE = "marketing-unsubscribe"
_KEY_LABEL = b"northstar.site-marketing.unsubscribe.v1\0"
_MAX_TOKEN_LENGTH = 750
_LINK_LIFETIME = timedelta(days=30)


@dataclass(frozen=True)
class UnsubscribeTarget:
    tenant_id: UUID
    workspace_id: UUID
    lead_id: UUID
    expires_at: datetime


class InvalidUnsubscribeToken(ValueError):
    """The supplied link is malformed, tampered with, or expired."""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    if not value or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        raise InvalidUnsubscribeToken("Malformed link")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise InvalidUnsubscribeToken("Malformed link") from exc


def _sign(secret: str, message: bytes) -> bytes:
    if len(secret) < 32:
        raise ValueError("A 32-character application secret is required")
    key = hmac.new(secret.encode("utf-8"), _KEY_LABEL, hashlib.sha256).digest()
    return hmac.new(key, message, hashlib.sha256).digest()


def make_unsubscribe_token(
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    lead_id: UUID,
    secret: str,
    now: datetime | None = None,
) -> str:
    issued = (now or datetime.now(UTC)).astimezone(UTC)
    body = {
        "v": 1,
        "p": _TOKEN_PURPOSE,
        "t": str(tenant_id),
        "w": str(workspace_id),
        "l": str(lead_id),
        "exp": int((issued + _LINK_LIFETIME).timestamp()),
    }
    payload = _b64(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _b64(_sign(secret, payload.encode("ascii")))
    return payload + "." + signature


def verify_unsubscribe_token(
    token: str, *, secret: str, now: datetime | None = None,
) -> UnsubscribeTarget:
    if len(token) > _MAX_TOKEN_LENGTH or token.count(".") != 1:
        raise InvalidUnsubscribeToken("Invalid link")
    data, mac = token.split(".", 1)
    try:
        payload = _unb64(data)
        supplied_mac = _unb64(mac)
        valid_mac = _sign(secret, data.encode("ascii"))
        if not hmac.compare_digest(supplied_mac, valid_mac):
            raise InvalidUnsubscribeToken("Invalid signature")
        body = json.loads(payload)
        if not isinstance(body, dict) or set(body) != {"v", "p", "t", "w", "l", "exp"}:
            raise InvalidUnsubscribeToken("Unsupported link")
        if body["v"] != 1 or body["p"] != _TOKEN_PURPOSE or type(body["exp"]) is not int:
            raise InvalidUnsubscribeToken("Unsupported link")
        current = (now or datetime.now(UTC)).astimezone(UTC)
        expires = datetime.fromtimestamp(body["exp"], tz=UTC)
        if expires <= current or expires - current > _LINK_LIFETIME + timedelta(minutes=1):
            raise InvalidUnsubscribeToken("Link expired")
        return UnsubscribeTarget(
            tenant_id=UUID(body["t"]), workspace_id=UUID(body["w"]),
            lead_id=UUID(body["l"]), expires_at=expires,
        )
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise InvalidUnsubscribeToken("Invalid or expired link") from exc



async def has_workspace_marketing_suppression(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    email: str | None,
    exclude_lead_id: UUID | None = None,
) -> bool:
    """An email withdrawal applies to all matching Leads in this workspace.

    Marketing permission is never inferred from a separate processing consent
    or reset by creating another Lead with the same email. The lookup uses only
    the existing Lead and LeadConsent records; no shadow suppression table.
    """
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return False
    query = (
        select(LeadConsent.id)
        .join(Lead, Lead.id == LeadConsent.lead_id)
        .where(
            Lead.tenant_id == tenant_id,
            Lead.workspace_id == workspace_id,
            LeadConsent.tenant_id == tenant_id,
            LeadConsent.consent_type == "marketing",
            func.lower(LeadConsent.status).in_(MARKETING_STOP_STATUSES),
            func.lower(Lead.email) == normalized_email,
        )
    )
    if exclude_lead_id is not None:
        query = query.where(Lead.id != exclude_lead_id)
    return await session.scalar(query.limit(1)) is not None
