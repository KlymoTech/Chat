"""Privileged certification evidence admission; never issues or signs proofs.

Only a separately authenticated certification pipeline may call this service.
Imported evidence remains unapproved until an independent governance approval.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .qualification import verify_qualification_proofs
from .queue_notification_qualification_persistence import NotificationWorkerQualificationRecord
from .queue_notification_worker_qualification import PersistedNotificationWorkerQualification

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


async def admit_notification_qualification(
    session: AsyncSession, *,
    qualification_id: str,
    environment: str,
    source_digest: str,
    target_digest: str,
    proof_tokens: tuple[str, ...],
    signing_key: bytes,
    pipeline_authorized: bool,
) -> None:
    """Insert a new immutable, unapproved evidence record in caller transaction.

    A duplicate ID fails via the primary key; there is no replace or upsert.
    The caller owns transaction commit, provenance audit and IAM authentication.
    """
    if not pipeline_authorized:
        raise PermissionError("external certification pipeline authorization required")
    if (
        not 8 <= len(qualification_id) <= 128
        or not 1 <= len(environment) <= 32
        or _DIGEST.fullmatch(source_digest) is None
        or _DIGEST.fullmatch(target_digest) is None
        or not 3 <= len(proof_tokens) <= 16
        or not all(isinstance(token, str) and len(token) <= 8192 for token in proof_tokens)
        or len(signing_key) < 32
    ):
        raise ValueError("invalid qualification evidence")
    blockers = verify_qualification_proofs(
        proof_tokens,
        required=PersistedNotificationWorkerQualification.REQUIRED,
        environment=environment,
        source_digest=source_digest,
        target_digest=target_digest,
        signing_key=signing_key,
    )
    if blockers:
        raise ValueError("qualification signature or binding verification failed")

    session.add(NotificationWorkerQualificationRecord(
        id=qualification_id,
        environment=environment,
        source_digest=source_digest,
        target_digest=target_digest,
        proof_tokens=list(proof_tokens),
        approved=False,
        revoked=False,
        created_at=datetime.now(UTC),
    ))
    await session.flush()
