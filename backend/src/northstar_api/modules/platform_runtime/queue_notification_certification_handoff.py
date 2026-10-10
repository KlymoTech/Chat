"""Fail-closed handoff from independent Jenkins attestations to pending evidence.

This module never starts a worker, grants approval, commits a database
transaction, or exposes a tenant-facing endpoint. The caller must be an isolated
certification service with a pinned test-runner public key and pinned AWS
workload signing-key adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from .queue_notification_certification_attestation import (
    QualificationSigningKeyStore,
    verify_jenkins_certification_result,
)
from .queue_notification_qualification_ingestion import ingest_notification_qualification
from .queue_notification_qualification_issuer import issue_notification_qualification_proofs
from .queue_notification_worker_qualification import NotificationQualificationRecord


@dataclass(frozen=True)
class PendingNotificationQualification:
    qualification_id: str
    run_id: str
    status: Literal["pending"] = "pending"


async def stage_verified_notification_qualification(
    session: AsyncSession,
    *,
    attestation_token: str,
    test_runner_public_key_pem: bytes,
    signing_key_store: QualificationSigningKeyStore,
    issuer: str,
    run_id: str,
    branch: str,
    environment: str,
    source_commit: str,
    source_digest: str,
    target_digest: str,
    now: datetime | None = None,
) -> PendingNotificationQualification:
    """Stage pending proofs for this exact Jenkins run in the caller's transaction.

    A stable primary key makes retries for the same run conflict rather than
    silently replacing evidence. The caller must roll back on *any* failure.
    External Jenkins runner authentication and immutable build artifacts are
    independent requirements, not inferred from the caller's parameters.
    """
    instant = now or datetime.now(UTC)
    kinds = verify_jenkins_certification_result(
        attestation_token,
        test_runner_public_key_pem=test_runner_public_key_pem,
        issuer=issuer,
        run_id=run_id,
        branch=branch,
        environment=environment,
        source_commit=source_commit,
        source_digest=source_digest,
        target_digest=target_digest,
        now=instant,
    )
    actor_id = f"jenkins:{issuer}"
    if len(actor_id) > 128:
        raise ValueError("certification issuer identity exceeds storage limit")

    key = await signing_key_store.retrieve(run_id=run_id)
    if key is None:
        raise PermissionError("qualified issuer signing key unavailable")
    proofs = issue_notification_qualification_proofs(
        environment=environment,
        source_digest=source_digest,
        target_digest=target_digest,
        run_id=run_id,
        signing_key=key,
        certified_kinds=kinds,
        certification_passed=True,
        trusted_issuer=True,
        now=instant,
    )
    qualification_id = f"jenkins:{run_id}"
    await ingest_notification_qualification(
        session,
        evidence=NotificationQualificationRecord(
            id=qualification_id,
            environment=environment,
            source_digest=source_digest,
            target_digest=target_digest,
            proof_tokens=proofs,
            approved=False,
            revoked=False,
        ),
        trusted_pipeline=True,
        signing_key=key,
        pipeline_actor_id=actor_id,
    )
    return PendingNotificationQualification(
        qualification_id=qualification_id, run_id=run_id
    )
