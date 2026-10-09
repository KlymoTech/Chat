"""Audited, revision-fenced certification approval and irreversible revocation.

Authentication and actor permissions belong to an isolated platform control-plane
caller; these functions demand an explicit authorization decision. Caller owns
transaction, and audit callback must use the same session.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .queue_notification_qualification_persistence import NotificationWorkerQualificationRecord

Audit = Callable[[AsyncSession, dict[str, str]], Awaitable[None]]


class QualificationGovernanceConflict(ValueError):
    pass


async def change_qualification_status(
    session: AsyncSession, *, qualification_id: str, expected_revision: int,
    actor_id: str, authorized: bool, action: str, audit: Audit,
) -> int:
    if not authorized:
        raise PermissionError("qualification governance permission required")
    if audit is None:
        raise ValueError("transactional audit required")
    if not qualification_id or not actor_id or len(actor_id) > 128 or expected_revision < 1:
        raise ValueError("invalid qualification governance input")
    if action not in {"approve", "revoke"}:
        raise ValueError("unsupported qualification transition")

    conditions = [
        NotificationWorkerQualificationRecord.id == qualification_id,
        NotificationWorkerQualificationRecord.revision == expected_revision,
        NotificationWorkerQualificationRecord.revoked.is_(False),
    ]
    if action == "approve":
        conditions.extend([
            NotificationWorkerQualificationRecord.approved.is_(False),
            NotificationWorkerQualificationRecord.issued_by.is_not(None),
            NotificationWorkerQualificationRecord.issued_by != actor_id,
            NotificationWorkerQualificationRecord.approved_by.is_(None),
        ])
        values = {"approved": True, "approved_by": actor_id}
    else:
        # Both pending and approved records may be revoked by independent
        # governance. A revoked evidence ID cannot be reapproved or reused.
        values = {"revoked": True, "revoked_by": actor_id, "approved": False}
    next_revision = expected_revision + 1
    result = await session.execute(
        update(NotificationWorkerQualificationRecord)
        .where(*conditions)
        .values(**values, revision=next_revision)
    )
    if result.rowcount != 1:
        raise QualificationGovernanceConflict("qualification transition conflict")
    await audit(session, {
        "action": "platform.notification_qualification." + action,
        "qualification_id": qualification_id,
        "revision": str(next_revision),
        "actor_id": actor_id,
    })
    return next_revision
