"""Publish independent Jenkins test evidence through the protected AWS publisher.

The test-runner signer and the S3 publisher have different security roles.
This component does not mint a signature, issue qualification proofs, approve
a release, mutate infrastructure, or start notification workers.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol

from .aws_immutable_certification_artifact_store import CertificationArtifactReceipt
from .aws_jenkins_evidence_publisher import ProtectedReleaseCoordinates, PublicationIdentity
from .queue_notification_certification_attestation import (
    CertificationAttestationError,
    verify_jenkins_certification_result,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class AttestationArchive(Protocol):
    async def archive_attestation(
        self, *, release_id: str, attestation_token: str,
        test_runner_public_key_pem: bytes, issuer: str, run_id: str,
        branch: str, environment: str, source_commit: str,
        source_digest: str, target_digest: str,
        now: datetime | None = None,
    ) -> CertificationArtifactReceipt: ...


class AttestationReadback(Protocol):
    async def reconcile(
        self, *, receipt: CertificationArtifactReceipt,
        release_id: str, attestation_token: str,
        test_runner_public_key_pem: bytes, issuer: str, run_id: str,
        branch: str, environment: str, source_commit: str,
        source_digest: str, target_digest: str,
        now: datetime | None = None,
    ) -> CertificationArtifactReceipt: ...


class AttestationPublicationUnconfirmed(RuntimeError):
    """The S3 attestation write did not yield a verified immutable version."""


async def publish_verified_jenkins_attestation(
    *, identity: PublicationIdentity,
    attestation_store: AttestationArchive,
    attestation_reconciler: AttestationReadback,
    plan: ProtectedReleaseCoordinates,
    attestation_token: str,
    test_runner_public_key_pem: bytes,
    test_runner_issuer: str,
    now: datetime | None = None,
) -> CertificationArtifactReceipt:
    """Store only passing, exact-build, signed tests with AWS publisher identity.

    The run, branch and release values must originate from a protected
    immutable build plan. The returned receipt can later be included in the
    *separately signed* release manifest. No S3 write is retried: unknown
    network outcomes must be reconciled by an independent operator.
    """
    if not await identity.verify(run_id=plan.run_id, branch=plan.branch):
        raise PermissionError("protected Jenkins evidence publisher identity required")
    if (
        not _SHA.fullmatch(plan.source_commit)
        or not _IMAGE.fullmatch(plan.image_digest)
    ):
        raise CertificationAttestationError("invalid protected build coordinates")
    verify_jenkins_certification_result(
        attestation_token,
        test_runner_public_key_pem=test_runner_public_key_pem,
        issuer=test_runner_issuer,
        run_id=plan.run_id,
        branch=plan.branch,
        environment=plan.environment,
        source_commit=plan.source_commit,
        source_digest=plan.source_digest,
        target_digest=plan.target_digest,
        now=now,
    )
    receipt = await attestation_store.archive_attestation(
        release_id=plan.release_id,
        attestation_token=attestation_token,
        test_runner_public_key_pem=test_runner_public_key_pem,
        issuer=test_runner_issuer,
        run_id=plan.run_id,
        branch=plan.branch,
        environment=plan.environment,
        source_commit=plan.source_commit,
        source_digest=plan.source_digest,
        target_digest=plan.target_digest,
        now=now,
    )
    try:
        confirmed = await attestation_reconciler.reconcile(
            receipt=receipt,
            release_id=plan.release_id,
            attestation_token=attestation_token,
            test_runner_public_key_pem=test_runner_public_key_pem,
            issuer=test_runner_issuer,
            run_id=plan.run_id,
            branch=plan.branch,
            environment=plan.environment,
            source_commit=plan.source_commit,
            source_digest=plan.source_digest,
            target_digest=plan.target_digest,
            now=now,
        )
    except Exception as exc:
        raise AttestationPublicationUnconfirmed(
            "signed Jenkins evidence write was not independently confirmed"
        ) from exc
    if confirmed != receipt:
        raise AttestationPublicationUnconfirmed(
            "attestation readback does not match original S3 version receipt"
        )
    return receipt
