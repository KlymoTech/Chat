"""Independently verified, append-only custody of Jenkins JUnit evidence.

Use this privileged service only with a protected build plan, a trusted AWS
publisher identity and an application DB transaction. A caller may stage
custody only after the index and all three report versions pass S3 readback.
Later consumers reconstruct version receipts and signed witness from the
persisted record, never from caller-supplied S3 object content or latest keys.

No signing, approval, deployment, worker activation, upsert or commit occurs.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .aws_immutable_jenkins_junit_store import JenkinsJunitReceipt
from .aws_jenkins_evidence_publisher import PublicationIdentity
from .aws_jenkins_junit_evidence_index import (
    JenkinsJunitIndexReceipt,
    WitnessedReportReconciler,
)
from .queue_notification_jenkins_junit_custody_persistence import (
    NotificationJenkinsJunitCustodyRecord,
)
from .queue_notification_jenkins_test_provenance import VerifiedJenkinsProvenance

_SUITES = frozenset({"notification_egress", "notification_secrets", "notification_worker"})
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")


class JenkinsJunitCustodyRejected(ValueError):
    """The immutable indexed evidence does not match the protected build plan."""


class JunitEvidenceIndexReconciler(Protocol):
    async def reconcile(
        self, *, index_receipt: JenkinsJunitIndexReceipt,
        report_reconciler: WitnessedReportReconciler,
        receipts: Mapping[str, JenkinsJunitReceipt],
        release_id: str, witness_token: str,
        witness_public_key_pem: bytes,
        attestation_signer_public_key_pem: bytes,
        witness_issuer: str, controller_id: str, job_full_name: str,
        run_id: str, branch: str, environment: str,
        source_commit: str, source_digest: str, target_digest: str,
        now: datetime | None = None,
    ) -> VerifiedJenkinsProvenance: ...


def _compare(
    verified: VerifiedJenkinsProvenance, *,
    run_id: str, branch: str, environment: str,
    source_commit: str, source_digest: str, target_digest: str,
) -> None:
    if (
        not isinstance(verified, VerifiedJenkinsProvenance)
        or verified.run_id != run_id
        or verified.branch != branch
        or verified.environment != environment
        or verified.source_commit != source_commit
        or verified.source_digest != source_digest
        or verified.target_digest != target_digest
        or not isinstance(verified.witness_sha256, str)
        or _SHA.fullmatch(verified.witness_sha256) is None
    ):
        raise JenkinsJunitCustodyRejected("verified evidence does not match protected release")


def _restore_receipts(
    raw: object, *, bucket: str, release_id: str, run_id: str,
) -> dict[str, JenkinsJunitReceipt]:
    if not isinstance(raw, dict) or frozenset(raw) != _SUITES:
        raise JenkinsJunitCustodyRejected("persisted JUnit receipt set is incomplete")
    recovered: dict[str, JenkinsJunitReceipt] = {}
    for name in sorted(_SUITES):
        item = raw[name]
        if not isinstance(item, dict) or set(item) != {
            "bucket", "key", "version_id", "sha256"
        }:
            raise JenkinsJunitCustodyRejected("invalid persisted JUnit receipt")
        item_values = list(item.values())
        if not all(isinstance(v, str) for v in item_values):
            raise JenkinsJunitCustodyRejected("invalid persisted S3 receipt field")
        receipt = JenkinsJunitReceipt(**item)
        if (
            receipt.bucket != bucket
            or receipt.key != f"evidence/{release_id}/jenkins/{run_id}/junit/{name}.xml"
            or not 1 <= len(receipt.version_id) <= 255
            or _SHA.fullmatch(receipt.sha256) is None
        ):
            raise JenkinsJunitCustodyRejected("persisted S3 version is not bound to release")
        recovered[name] = receipt
    return recovered


async def stage_witnessed_junit_custody(
    session: AsyncSession, *,
    identity: PublicationIdentity,
    index_reconciler: JunitEvidenceIndexReconciler,
    report_reconciler: object,
    index_receipt: JenkinsJunitIndexReceipt,
    receipts: Mapping[str, JenkinsJunitReceipt],
    release_id: str, witness_token: str,
    witness_public_key_pem: bytes,
    attestation_signer_public_key_pem: bytes,
    witness_issuer: str, controller_id: str, job_full_name: str,
    run_id: str, branch: str, environment: str,
    source_commit: str, source_digest: str, target_digest: str,
    now: datetime | None = None,
) -> JenkinsJunitIndexReceipt:
    """Stage a write-once DB receipt, then let the caller commit atomically.

    S3 evidence is reverified before DB mutation. A concurrent attempt to
    rebind the same run or release fails via PostgreSQL primary/unique keys.
    """
    if not await identity.verify(run_id=run_id, branch=branch):
        raise PermissionError("qualified Jenkins evidence custodian identity required")
    if not isinstance(release_id, str) or _RELEASE.fullmatch(release_id) is None:
        raise JenkinsJunitCustodyRejected("invalid protected release ID")
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise JenkinsJunitCustodyRejected("timezone-aware custody required")
    if (
        not isinstance(index_receipt, JenkinsJunitIndexReceipt)
        or not isinstance(index_receipt.bucket, str)
        or not isinstance(index_receipt.key, str)
        or not isinstance(index_receipt.version_id, str)
        or not 1 <= len(index_receipt.version_id) <= 255
        or not isinstance(index_receipt.sha256, str)
        or _SHA.fullmatch(index_receipt.sha256) is None
    ):
        raise JenkinsJunitCustodyRejected("original evidence index receipt is not pinned")
    if not isinstance(receipts, Mapping) or frozenset(receipts) != _SUITES:
        raise JenkinsJunitCustodyRejected("original JUnit receipts must be complete")
    if any(not isinstance(value, JenkinsJunitReceipt) for value in receipts.values()):
        raise JenkinsJunitCustodyRejected("original JUnit receipt type mismatch")
    frozen_receipts = _restore_receipts(
        {key: asdict(value) for key, value in receipts.items()},
        bucket=index_receipt.bucket, release_id=release_id, run_id=run_id,
    )
    if (
        index_receipt.key != f"evidence/{release_id}/jenkins/{run_id}/junit/verified-index.json"
        or not isinstance(witness_token, str)
        or not 1 <= len(witness_token) <= 16384
    ):
        raise JenkinsJunitCustodyRejected("evidence index not bound to release")
    verified = await index_reconciler.reconcile(
        index_receipt=index_receipt, report_reconciler=report_reconciler,
        receipts=frozen_receipts, release_id=release_id, witness_token=witness_token,
        witness_public_key_pem=witness_public_key_pem,
        attestation_signer_public_key_pem=attestation_signer_public_key_pem,
        witness_issuer=witness_issuer, controller_id=controller_id,
        job_full_name=job_full_name, run_id=run_id, branch=branch,
        environment=environment, source_commit=source_commit,
        source_digest=source_digest, target_digest=target_digest, now=instant,
    )
    _compare(
        verified, run_id=run_id, branch=branch, environment=environment,
        source_commit=source_commit, source_digest=source_digest,
        target_digest=target_digest,
    )
    session.add(NotificationJenkinsJunitCustodyRecord(
        release_id=release_id, run_id=run_id, branch=branch,
        environment=environment, source_commit=source_commit,
        source_digest=source_digest, target_digest=target_digest,
        witness_token=witness_token, witness_sha256=verified.witness_sha256,
        index_bucket=index_receipt.bucket, index_key=index_receipt.key,
        index_version_id=index_receipt.version_id,
        index_sha256=index_receipt.sha256,
        suite_receipts={
            name: asdict(frozen_receipts[name]) for name in sorted(_SUITES)
        },
        created_at=instant,
    ))
    await session.flush()
    return index_receipt


async def load_and_reconcile_witnessed_junit_custody(
    session: AsyncSession, *,
    index_reconciler: JunitEvidenceIndexReconciler,
    report_reconciler: object,
    release_id: str, run_id: str, branch: str,
    environment: str, source_commit: str,
    source_digest: str, target_digest: str,
    witness_public_key_pem: bytes,
    attestation_signer_public_key_pem: bytes,
    witness_issuer: str, controller_id: str, job_full_name: str,
    now: datetime | None = None,
) -> VerifiedJenkinsProvenance:
    """Reverify ONLY persisted, immutable receipt identities against S3.

    A protected caller supplies expected run/build coordinates and pinned
    public keys; it cannot replace the witness token or stored receipts.
    """
    if not isinstance(release_id, str) or _RELEASE.fullmatch(release_id) is None:
        raise JenkinsJunitCustodyRejected("invalid release identifier")
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise JenkinsJunitCustodyRejected("timezone-aware custody required")
    row = await session.get(NotificationJenkinsJunitCustodyRecord, release_id)
    if (
        row is None
        or row.run_id != run_id
        or row.branch != branch
        or row.environment != environment
        or row.source_commit != source_commit
        or row.source_digest != source_digest
        or row.target_digest != target_digest
        or not isinstance(row.witness_sha256, str)
        or _SHA.fullmatch(row.witness_sha256) is None
        or not isinstance(row.witness_token, str)
        or not 1 <= len(row.witness_token) <= 16384
        or not isinstance(row.index_bucket, str)
        or not isinstance(row.index_key, str)
        or row.index_key != (
            f"evidence/{release_id}/jenkins/{run_id}/junit/verified-index.json"
        )
        or not isinstance(row.index_version_id, str)
        or not 1 <= len(row.index_version_id) <= 255
        or not isinstance(row.index_sha256, str)
        or _SHA.fullmatch(row.index_sha256) is None
    ):
        raise JenkinsJunitCustodyRejected("persisted evidence not bound to approved run")
    index_receipt = JenkinsJunitIndexReceipt(
        bucket=row.index_bucket,
        key=row.index_key,
        version_id=row.index_version_id,
        sha256=row.index_sha256,
    )
    receipts = _restore_receipts(
        row.suite_receipts, bucket=row.index_bucket,
        release_id=release_id, run_id=run_id,
    )
    verified = await index_reconciler.reconcile(
        index_receipt=index_receipt, report_reconciler=report_reconciler,
        receipts=receipts, release_id=release_id,
        witness_token=row.witness_token,
        witness_public_key_pem=witness_public_key_pem,
        attestation_signer_public_key_pem=attestation_signer_public_key_pem,
        witness_issuer=witness_issuer, controller_id=controller_id,
        job_full_name=job_full_name, run_id=run_id, branch=branch,
        environment=environment, source_commit=source_commit,
        source_digest=source_digest, target_digest=target_digest,
        now=instant,
    )
    _compare(
        verified, run_id=run_id, branch=branch, environment=environment,
        source_commit=source_commit, source_digest=source_digest,
        target_digest=target_digest,
    )
    if verified.witness_sha256 != row.witness_sha256:
        raise JenkinsJunitCustodyRejected("original witnessed report digest differs")
    return verified
