"""Stage and consume independently verified Jenkins evidence custody.

Only a protected publisher writes the append-only database record. A signer
must look up the receipts by protected release ID, never accept caller-supplied
S3 versions. Every read re-verifies locked S3 bytes and the signed witness.
This service cannot sign, approve, activate, or deploy.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from .aws_immutable_jenkins_junit_store import JenkinsJunitReceipt
from .aws_jenkins_evidence_publisher import PublicationIdentity
from .aws_jenkins_junit_evidence_index import (
    AwsJenkinsJunitEvidenceIndex,
    JenkinsJunitIndexReceipt,
    WitnessedReportReconciler,
)
from .queue_notification_jenkins_test_provenance import VerifiedJenkinsProvenance
from .queue_notification_junit_index_custody_persistence import NotificationJunitIndexCustody

_NAMES = ("notification_egress", "notification_secrets", "notification_worker")


class JunitCustodyRejected(ValueError):
    """The original release, run and independently verified evidence disagree."""


def _record_receipts(record: NotificationJunitIndexCustody) -> dict[str, JenkinsJunitReceipt]:
    return {
        "notification_worker": JenkinsJunitReceipt(
            record.worker_bucket, record.worker_key, record.worker_version_id, record.worker_sha256,
        ),
        "notification_egress": JenkinsJunitReceipt(
            record.egress_bucket, record.egress_key, record.egress_version_id, record.egress_sha256,
        ),
        "notification_secrets": JenkinsJunitReceipt(
            record.secrets_bucket, record.secrets_key, record.secrets_version_id, record.secrets_sha256,
        ),
    }


def _index_receipt(record: NotificationJunitIndexCustody) -> JenkinsJunitIndexReceipt:
    return JenkinsJunitIndexReceipt(
        record.index_bucket, record.index_key, record.index_version_id, record.index_sha256,
    )


async def stage_witnessed_junit_custody(
    session: AsyncSession,
    *,
    identity: PublicationIdentity,
    index: AwsJenkinsJunitEvidenceIndex,
    report_reconciler: WitnessedReportReconciler,
    index_receipt: JenkinsJunitIndexReceipt,
    receipts: Mapping[str, JenkinsJunitReceipt],
    release_id: str,
    witness_token: str,
    witness_public_key_pem: bytes,
    attestation_signer_public_key_pem: bytes,
    witness_issuer: str,
    controller_id: str,
    job_full_name: str,
    run_id: str,
    branch: str,
    environment: str,
    source_commit: str,
    source_digest: str,
    target_digest: str,
    now: datetime | None = None,
) -> None:
    """Validate both S3 layers before inserting one immutable custody row.

    Caller controls commit/rollback and must use a separately authenticated
    privileged DB principal. No upsert, replace, auto-retry or commit occurs.
    """
    if not await identity.verify(run_id=run_id, branch=branch):
        raise PermissionError("protected Jenkins custody publisher identity required")
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise JunitCustodyRejected("timezone-aware custody required")
    verified = await index.reconcile(
        index_receipt=index_receipt,
        report_reconciler=report_reconciler,
        receipts=receipts,
        release_id=release_id,
        witness_token=witness_token,
        witness_public_key_pem=witness_public_key_pem,
        attestation_signer_public_key_pem=attestation_signer_public_key_pem,
        witness_issuer=witness_issuer,
        controller_id=controller_id,
        job_full_name=job_full_name,
        run_id=run_id,
        branch=branch,
        environment=environment,
        source_commit=source_commit,
        source_digest=source_digest,
        target_digest=target_digest,
        now=instant,
    )
    if (
        verified.run_id != run_id
        or verified.branch != branch
        or verified.environment != environment
        or verified.source_commit != source_commit
        or verified.source_digest != source_digest
        or verified.target_digest != target_digest
        or frozenset(receipts) != frozenset(_NAMES)
        or index_receipt.bucket != receipts["notification_worker"].bucket
        or any(receipts[name].bucket != index_receipt.bucket for name in _NAMES)
    ):
        raise JunitCustodyRejected("witnessed evidence cannot be bound to this release/run")
    worker, egress, secrets = (receipts[name] for name in
                               ("notification_worker", "notification_egress", "notification_secrets"))
    session.add(NotificationJunitIndexCustody(
        release_id=release_id,
        run_id=run_id,
        branch=branch,
        environment=environment,
        source_commit=source_commit,
        source_digest=source_digest,
        target_digest=target_digest,
        witness_sha256=verified.witness_sha256,
        index_bucket=index_receipt.bucket,
        index_key=index_receipt.key,
        index_version_id=index_receipt.version_id,
        index_sha256=index_receipt.sha256,
        worker_bucket=worker.bucket, worker_key=worker.key,
        worker_version_id=worker.version_id, worker_sha256=worker.sha256,
        egress_bucket=egress.bucket, egress_key=egress.key,
        egress_version_id=egress.version_id, egress_sha256=egress.sha256,
        secrets_bucket=secrets.bucket, secrets_key=secrets.key,
        secrets_version_id=secrets.version_id, secrets_sha256=secrets.sha256,
        created_at=instant,
    ))
    await session.flush()


async def verify_custodied_junit_evidence(
    session: AsyncSession,
    *,
    index: AwsJenkinsJunitEvidenceIndex,
    report_reconciler: WitnessedReportReconciler,
    release_id: str,
    run_id: str,
    branch: str,
    environment: str,
    source_commit: str,
    source_digest: str,
    target_digest: str,
    witness_token: str,
    witness_public_key_pem: bytes,
    attestation_signer_public_key_pem: bytes,
    witness_issuer: str,
    controller_id: str,
    job_full_name: str,
    now: datetime | None = None,
) -> VerifiedJenkinsProvenance:
    """Only DB-owned receipts may authorize subsequent internal signing.

    The signed witness is separately authenticated during locked S3 readback.
    The caller's witness token must match the original witnessed digest,
    never replace it. Signer private keys are not accessed here.
    """
    record = await session.get(NotificationJunitIndexCustody, release_id)
    if (
        record is None
        or record.run_id != run_id
        or record.branch != branch
        or record.environment != environment
        or record.source_commit != source_commit
        or record.source_digest != source_digest
        or record.target_digest != target_digest
    ):
        raise JunitCustodyRejected("no matching protected release/run receipt custody")
    verified = await index.reconcile(
        index_receipt=_index_receipt(record),
        report_reconciler=report_reconciler,
        receipts=_record_receipts(record),
        release_id=release_id,
        witness_token=witness_token,
        witness_public_key_pem=witness_public_key_pem,
        attestation_signer_public_key_pem=attestation_signer_public_key_pem,
        witness_issuer=witness_issuer,
        controller_id=controller_id,
        job_full_name=job_full_name,
        run_id=run_id,
        branch=branch,
        environment=environment,
        source_commit=source_commit,
        source_digest=source_digest,
        target_digest=target_digest,
        now=now,
    )
    if verified.witness_sha256 != record.witness_sha256:
        raise JunitCustodyRejected("witness differs from retained custody")
    return verified
