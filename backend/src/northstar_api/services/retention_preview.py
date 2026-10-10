"""Read-only, tenant-scoped conversation retention discovery.

Never delete records from this module. Privacy-rights legal holds are owned by
another system and must be reconciled before any deletion executor is designed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

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


async def preview_conversation_retention(
    db: Any,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    as_of: datetime,
    max_rows: int = 500,
) -> RetentionPreview:
    """Read at most max_rows+1 records; no writes, no global/PII enumeration."""
    if not isinstance(tenant_id, UUID) or not isinstance(workspace_id, UUID):
        raise ValueError("tenant_id and workspace_id must be UUIDs")
    if type(max_rows) is not int or not 1 <= max_rows <= MAX_PREVIEW_ROWS:
        raise ValueError("retention preview max_rows must be in 1..1000")
    if _aware_utc(as_of) is None:
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
        )
        .order_by(Conversation.updated_at.asc(), Conversation.id.asc())
        .limit(max_rows + 1)
    )
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > max_rows
    candidates: list[UUID] = []
    held = invalid_policy = recent = 0

    for conversation_id, started_at, updated_at, message_at, security in rows[:max_rows]:
        if has_local_retention_hold(security):
            held += 1
            continue
        cutoff = retention_cutoff(security, as_of=as_of)
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

    return RetentionPreview(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        as_of=as_of.astimezone(UTC),
        inspected=min(max_rows, len(rows)),
        candidate_ids=tuple(candidates),
        held=held,
        invalid_policy=invalid_policy,
        recent=recent,
        truncated=truncated,
    )
