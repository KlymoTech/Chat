"""Read-only, tenant-scoped conversation retention discovery.

Never delete records from this module. Privacy-rights legal holds are owned by
another system and must be reconciled before any deletion executor is designed.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from northstar_api.models import Agent, Conversation, Message

MAX_PREVIEW_ROWS = 1_000


@dataclass(frozen=True)
class RetentionPreview:
    tenant_id: UUID
    workspace_id: UUID
    as_of: datetime
    inspected: int
    candidate_ids: tuple[UUID, ...]
    held: int
    invalid_policy: int
    recent: int
    truncated: bool
    # The website privacy-rights store has its own legal_hold state and is
    # not reconciled with these backend conversation tables.
    requires_external_legal_hold_review: bool = True
    next_cursor: str | None = None


def retention_cutoff(security: object, *, as_of: datetime) -> datetime | None:
    """Return a provisional expiration cutoff, never deletion authorization."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("retention preview requires timezone-aware now")
    if not isinstance(security, dict):
        return None
    days = security.get("retentionDays")
    if type(days) is not int or not 1 <= days <= 3_650:
        return None
    return as_of.astimezone(UTC) - timedelta(days=days)


def has_local_retention_hold(security: object) -> bool:
    """Conservatively block preview candidates with an explicit local hold."""
    return isinstance(security, dict) and any(
        name in security and security[name] is not False and security[name] is not None
        for name in ("legalHold", "retentionHold", "privacyHold")
    )


def _aware_utc(value: datetime) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


_CURSOR_FIELDS = frozenset(
    {"version", "tenant_id", "workspace_id", "as_of", "updated_at", "conversation_id"}
)


def _encode_cursor(
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    as_of: datetime,
    updated_at: datetime,
    conversation_id: UUID,
) -> str:
    stamp = _aware_utc(updated_at)
    if stamp is None:
        raise ValueError("Cannot continue retention preview after an invalid timestamp")
    data = {
        "version": 1,
        "tenant_id": str(tenant_id),
        "workspace_id": str(workspace_id),
        "as_of": as_of.isoformat(),
        "updated_at": stamp.isoformat(),
        "conversation_id": str(conversation_id),
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
) -> tuple[datetime, datetime, UUID]:
    """Validate a non-secret pagination position against its original scope."""
    if not isinstance(cursor, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", cursor):
        raise ValueError("Invalid retention pagination cursor")
    try:
        data = json.loads(
            base64.b64decode(
                cursor + "=" * (-len(cursor) % 4),
                altchars=b"-_",
                validate=True,
            )
        )
        if (
            type(data) is not dict
            or data.keys() != _CURSOR_FIELDS
            or type(data["version"]) is not int
            or data["version"] != 1
            or data["tenant_id"] != str(tenant_id)
            or data["workspace_id"] != str(workspace_id)
        ):
            raise ValueError("Cursor scope or version mismatch")
        as_of = datetime.fromisoformat(data["as_of"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        conversation_id = UUID(data["conversation_id"])
        normalized_as_of = _aware_utc(as_of)
        normalized_updated = _aware_utc(updated_at)
        if (
            normalized_as_of is None
            or normalized_updated is None
            or normalized_updated > normalized_as_of
            or str(conversation_id) != data["conversation_id"]
        ):
            raise ValueError("Cursor contains invalid timestamps or identifier")
        return normalized_as_of, normalized_updated, conversation_id
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as exc:
        raise ValueError("Invalid or out-of-scope retention pagination cursor") from exc


async def preview_conversation_retention(
    db: Any,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    as_of: datetime | None = None,
    max_rows: int = 500,
    cursor: str | None = None,
) -> RetentionPreview:
    """Read at most max_rows+1 records; no writes, no global/PII enumeration."""
    if not isinstance(tenant_id, UUID) or not isinstance(workspace_id, UUID):
        raise ValueError("tenant_id and workspace_id must be UUIDs")
    if type(max_rows) is not int or not 1 <= max_rows <= MAX_PREVIEW_ROWS:
        raise ValueError("retention preview max_rows must be in 1..1000")
    if cursor is not None:
        pinned_as_of, after_updated, after_id = _decode_cursor(
            cursor, tenant_id=tenant_id, workspace_id=workspace_id
        )
        if as_of is not None and _aware_utc(as_of) != pinned_as_of:
            raise ValueError("Continuation must preserve the original as_of")
        as_of_utc = pinned_as_of
    else:
        as_of_utc = _aware_utc(as_of if as_of is not None else datetime.now(UTC))
        after_updated = after_id = None
    if as_of_utc is None:
        raise ValueError("retention preview requires timezone-aware now")

    latest_message = (
        select(func.max(Message.created_at))
        .where(
            Message.conversation_id == Conversation.id,
            Message.tenant_id == tenant_id,
            Message.workspace_id == workspace_id,
        )
        .correlate(Conversation)
        .scalar_subquery()
    )
    stmt = (
        select(
            Conversation.id,
            Conversation.started_at,
            Conversation.updated_at,
            latest_message,
            Agent.security,
        )
        .join(
            Agent,
            (Conversation.agent_id == Agent.id)
            & (Agent.tenant_id == tenant_id)
            & (Agent.workspace_id == workspace_id),
        )
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.workspace_id == workspace_id,
            Conversation.updated_at <= as_of_utc,
        )
        .order_by(Conversation.updated_at.asc(), Conversation.id.asc())
        .limit(max_rows + 1)
    )
    if after_updated is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                Conversation.updated_at > after_updated,
                and_(
                    Conversation.updated_at == after_updated,
                    Conversation.id > after_id,
                ),
            )
        )
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > max_rows
    candidates: list[UUID] = []
    held = invalid_policy = recent = 0

    for conversation_id, started_at, updated_at, message_at, security in rows[:max_rows]:
        if has_local_retention_hold(security):
            held += 1
            continue
        cutoff = retention_cutoff(security, as_of=as_of_utc)
        started = _aware_utc(started_at)
        updated = _aware_utc(updated_at)
        latest = _aware_utc(message_at) if message_at is not None else None
        if (
            cutoff is None
            or started is None
            or updated is None
            or (message_at is not None and latest is None)
        ):
            invalid_policy += 1
        elif max(stamp for stamp in (started, updated, latest) if stamp is not None) < cutoff:
            candidates.append(conversation_id)
        else:
            recent += 1

    next_cursor = None
    if truncated:
        last_id, _, last_updated, _, _ = rows[max_rows - 1]
        if not isinstance(last_id, UUID):
            raise ValueError("Cannot continue retention preview after invalid row id")
        next_cursor = _encode_cursor(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            as_of=as_of_utc,
            updated_at=last_updated,
            conversation_id=last_id,
        )

    return RetentionPreview(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        as_of=as_of_utc,
        inspected=min(max_rows, len(rows)),
        candidate_ids=tuple(candidates),
        held=held,
        invalid_policy=invalid_policy,
        recent=recent,
        truncated=truncated,
        next_cursor=next_cursor,
    )
