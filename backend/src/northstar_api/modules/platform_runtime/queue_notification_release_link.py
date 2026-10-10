"""Bind verified immutable release artifacts to pending worker qualification.

This privileged, caller-transaction-owned service performs S3 read-only
qualification *before* locking a pending Jenkins evidence row. It never
commits, approves, revokes, or starts a worker. The two pinned S3 receipts and
independent signers must originate from the protected certification plane.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .aws_immutable_certification_artifact_store import CertificationArtifactReceipt
from .aws_immutable_release_manifest_store import ImmutableReleaseManifestReceipt
from .aws_release_manifest_reconciliation import ReadOnlyReleaseManifestReconciler
from .queue_notification_qualification_persistence import NotificationWorkerQualificationRecord
from .queue_notification_release_link_persistence import NotificationQualificationReleaseLink
from .queue_notification_release_manifest import (
    ArtifactReconciler,
    verify_manifest_and_reconcile_artifact,
)


class QualificationReleaseLinkRejected(ValueError):
    """The pending qualification and independently verified release differ."""


async def stage_qualification_release_link(
    session: AsyncSession,
    *,
    authorized_publisher: bool,
    qualification_id: str,
    manifest_receipt: ImmutableReleaseManifestReceipt,
    manifest_reconciler: ReadOnlyReleaseManifestReconciler,
    attestation_reconciler: ArtifactReconciler,
    manifest_token: str,
    release_signer_public_key_pem: bytes,
    release_issuer: str,
    test_runner_public_key_pem: bytes,
    attestation_issuer: str,
    attestation_token: str,
    attestation_receipt: CertificationArtifactReceipt,
    release_id: str,
    run_id: str,
    branch: str,
    environment: str,
    source_commit: str,
    image_digest: str,
    source_digest: str,
    target_digest: str,
    now: datetime | None = None,
) -> str:
    """Insert an append-only link after both S3 versions are re-verified.

    Caller is responsible for independent publisher authentication and for
    rollback on any storage, row, uniqueness or audit failure. The boolean
    parameter is only a defense-in-depth signal, not machine authentication.
    """
    if not authorized_publisher:
        raise PermissionError("qualified release publisher authorization required")
    if qualification_id != f"jenkins:{run_id}" or len(qualification_id) > 128:
        raise QualificationReleaseLinkRejected("qualification ID is not bound to Jenkins run")
    issuer_id = f"jenkins:{attestation_issuer}"
    if len(issuer_id) > 128:
        raise QualificationReleaseLinkRejected("Jenkins test issuer identity is too long")

    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise QualificationReleaseLinkRejected("timezone-aware qualification required")
    verified = await verify_manifest_and_reconcile_artifact(
        manifest_token,
        reconciler=attestation_reconciler,
        test_runner_public_key_pem=test_runner_public_key_pem,
        attestation_issuer=attestation_issuer,
        release_signer_public_key_pem=release_signer_public_key_pem,
        trusted_issuer=release_issuer,
        release_id=release_id,
        run_id=run_id,
        branch=branch,
        environment=environment,
        source_commit=source_commit,
        image_digest=image_digest,
        source_digest=source_digest,
        target_digest=target_digest,
        attestation_token=attestation_token,
        artifact_receipt=attestation_receipt,
        now=instant,
    )
    confirmed = await manifest_reconciler.reconcile(
        receipt=manifest_receipt,
        manifest_token=manifest_token,
        release_signer_public_key_pem=release_signer_public_key_pem,
        trusted_issuer=release_issuer,
        release_id=release_id,
        run_id=run_id,
        branch=branch,
        environment=environment,
        source_commit=source_commit,
        image_digest=image_digest,
        source_digest=source_digest,
        target_digest=target_digest,
        attestation_token=attestation_token,
        artifact_receipt=attestation_receipt,
        now=instant,
    )
    if confirmed != manifest_receipt:
        raise QualificationReleaseLinkRejected("release manifest version was not confirmed")

    record = await session.get(
        NotificationWorkerQualificationRecord, qualification_id,
        with_for_update=True,
    )
    if (
        record is None
        or record.approved or record.revoked
        or record.revision != 1
        or record.issued_by != issuer_id
        or record.environment != verified.environment
        or record.source_digest != source_digest
        or record.target_digest != target_digest
        or not isinstance(record.proof_tokens, list)
        or len(record.proof_tokens) < 3
    ):
        raise QualificationReleaseLinkRejected("pending qualification cannot be linked to release")

    session.add(NotificationQualificationReleaseLink(
        qualification_id=qualification_id,
        release_id=verified.release_id,
        run_id=run_id,
        environment=verified.environment,
        source_commit=verified.source_commit,
        image_digest=verified.image_digest,
        source_digest=source_digest,
        target_digest=target_digest,
        signed_manifest_sha256=verified.manifest_sha256,
        manifest_bucket=manifest_receipt.bucket,
        manifest_key=manifest_receipt.key,
        manifest_version_id=manifest_receipt.version_id,
        manifest_object_sha256=manifest_receipt.sha256,
        attestation_bucket=attestation_receipt.bucket,
        attestation_key=attestation_receipt.key,
        attestation_version_id=attestation_receipt.version_id,
        attestation_sha256=attestation_receipt.sha256,
        created_at=instant,
    ))
    # Primary/unique constraints reject re-linking to a new proof in the
    # caller's transaction; no UPSERT/REPLACE or commit is performed.
    await session.flush()
    return qualification_id
