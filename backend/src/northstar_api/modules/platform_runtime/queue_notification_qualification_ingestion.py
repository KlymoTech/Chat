"""Certification-only evidence ingestion; never grants worker approval.

An isolated certification controller must authenticate and authorize the caller.
Evidence is cryptographically verified before an immutable pending record is
inserted; approval/revocation is a separate audited governance workflow.
Do not expose this function through tenant or public API endpoints.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .qualification import verify_qualification_proofs
from .queue_notification_qualification_persistence import NotificationWorkerQualificationRecord
from .queue_notification_worker_qualification import (
    NotificationQualificationRecord,
    PersistedNotificationWorkerQualification,
)


class QualificationIngestionRejected(ValueError):
    """Evidence cannot be trusted; no record should be committed."""


async def ingest_notification_qualification(
    session: AsyncSession,
    *,
    evidence: NotificationQualificationRecord,
    trusted_pipeline: bool,
    signing_key: bytes,
    pipeline_actor_id: str | None = None,
) -> None:
    """Insert pending evidence under a caller-owned transaction.

    Database primary-key uniqueness prevents reuse of qualification IDs.
    Approval is always false regardless of the caller-provided value.
    """
    if not trusted_pipeline:
        raise PermissionError("certification pipeline authorization required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", evidence.id):
        raise QualificationIngestionRejected("invalid qualification ID")
    if (
        evidence.approved or evidence.revoked
        or not 1 <= len(evidence.proof_tokens) <= 16
        or any(len(t) > 8192 for t in evidence.proof_tokens)
    ):
        raise QualificationIngestionRejected("invalid pending evidence")
    blockers = verify_qualification_proofs(
        evidence.proof_tokens,
        required=PersistedNotificationWorkerQualification.REQUIRED,
        environment=evidence.environment,
        source_digest=evidence.source_digest,
        target_digest=evidence.target_digest,
        signing_key=signing_key,
    )
    if blockers:
        raise QualificationIngestionRejected("required certification proofs are missing or invalid")
    if pipeline_actor_id is not None and (not pipeline_actor_id.strip() or len(pipeline_actor_id) > 128):
        raise QualificationIngestionRejected("invalid certification actor")
    session.add(NotificationWorkerQualificationRecord(
        id=evidence.id,
        environment=evidence.environment,
        source_digest=evidence.source_digest,
        target_digest=evidence.target_digest,
        proof_tokens=list(evidence.proof_tokens),
        approved=False,
        revoked=False,
        revision=1,
        issued_by=pipeline_actor_id,
        created_at=datetime.now(UTC),
    ))
    # Flush uniqueness errors inside the caller-owned transaction. No commit here.
    await session.flush()
