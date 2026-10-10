"""Protected Jenkins release-evidence publisher boundary (never an API endpoint).

The publishing role is distinct from the independent test and release signers.
Only exact STS assumed-role build sessions may reach the existing locked-S3
writer. The publisher cannot mint signatures, change governance approval, or
activate a notification worker. Its caller must supply release coordinates from
a protected, immutable build plan rather than Jenkins user parameters.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import boto3
from botocore.config import Config

from .aws_immutable_certification_artifact_store import CertificationArtifactReceipt
from .aws_immutable_release_manifest_store import (
    AwsImmutableReleaseManifestStore,
    ImmutableReleaseManifestReceipt,
)
from .aws_release_manifest_reconciliation import ReadOnlyReleaseManifestReconciler
from .queue_notification_release_manifest import (
    ArtifactReconciler,
    ReleaseManifestRejected,
    verify_signed_release_manifest,
)

_ACCOUNT = re.compile(r"[0-9]{12}\Z")
_REGION = re.compile(r"[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+\Z")
_ROLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+=,.@_-]{1,63}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PublicationIdentity(Protocol):
    async def verify(self, *, run_id: str, branch: str) -> bool: ...


class EvidencePublicationUnconfirmed(RuntimeError):
    """Release evidence was not confirmed by exact S3-version read-back."""


@dataclass(frozen=True)
class ProtectedReleaseCoordinates:
    release_id: str
    run_id: str
    branch: str
    environment: str
    source_commit: str
    image_digest: str
    source_digest: str
    target_digest: str


class AwsJenkinsEvidencePublisherIdentity:
    """Check the *actual* AWS caller; never accept a role name from the job."""

    def __init__(
        self, *, account_id: str, region: str, role_name: str,
        allowed_branch: str, sts_client: Any = None,
        timeout_seconds: float = 4.0,
    ) -> None:
        if (
            not _ACCOUNT.fullmatch(account_id)
            or not _REGION.fullmatch(region)
            or not _ROLE.fullmatch(role_name)
            or not allowed_branch or len(allowed_branch) > 200
            or not 0 < timeout_seconds <= 15
        ):
            raise ValueError("invalid protected publisher identity configuration")
        self._account = account_id
        partition = "aws-us-gov" if region.startswith("us-gov-") else "aws"
        self._arn_prefix = f"arn:{partition}:sts::{account_id}:assumed-role/{role_name}/"
        self._branch = allowed_branch
        self._timeout = timeout_seconds
        self._sts = sts_client if sts_client is not None else boto3.client(
            "sts", region_name=region,
            config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 1}),
        )

    async def verify(self, *, run_id: str, branch: str) -> bool:
        if (
            not isinstance(run_id, str) or not _RUN.fullmatch(run_id)
            or branch != self._branch
        ):
            return False
        session = "northstar-evidence-" + run_id
        try:
            caller = await asyncio.wait_for(
                asyncio.to_thread(self._sts.get_caller_identity),
                timeout=self._timeout,
            )
            return bool(
                isinstance(caller, dict)
                and caller.get("Account") == self._account
                and caller.get("Arn") == self._arn_prefix + session
                and isinstance(caller.get("UserId"), str)
                and caller["UserId"].partition(":")[2] == session
            )
        except Exception:
            return False


async def publish_verified_release_manifest(
    *, identity: PublicationIdentity,
    manifest_store: AwsImmutableReleaseManifestStore,
    manifest_reconciler: ReadOnlyReleaseManifestReconciler,
    attestation_reconciler: ArtifactReconciler,
    plan: ProtectedReleaseCoordinates,
    manifest_token: str,
    attestation_token: str,
    attestation_receipt: CertificationArtifactReceipt,
    release_signer_public_key_pem: bytes,
    release_issuer: str,
    test_runner_public_key_pem: bytes,
    test_runner_issuer: str,
    now: datetime | None = None,
) -> ImmutableReleaseManifestReceipt:
    """Publish *already signed* release evidence and verify exact S3 version.

    The attestation must already exist with a pinned version receipt so its
    S3 version can be embedded in the externally signed manifest. There is no
    automatic retry after an unknown write, and no approval/database mutation.
    """
    if not await identity.verify(run_id=plan.run_id, branch=plan.branch):
        raise PermissionError("protected Jenkins evidence publisher identity required")
    if not _SHA.fullmatch(plan.source_commit) or not _IMAGE.fullmatch(plan.image_digest):
        raise ReleaseManifestRejected("untrusted source/image coordinates")
    verify_signed_release_manifest(
        manifest_token,
        release_signer_public_key_pem=release_signer_public_key_pem,
        trusted_issuer=release_issuer,
        release_id=plan.release_id,
        run_id=plan.run_id,
        branch=plan.branch,
        environment=plan.environment,
        source_commit=plan.source_commit,
        image_digest=plan.image_digest,
        source_digest=plan.source_digest,
        target_digest=plan.target_digest,
        attestation_token=attestation_token,
        artifact_receipt=attestation_receipt,
        now=now,
    )
    written = await manifest_store.archive_manifest(
        manifest_token=manifest_token,
        reconciler=attestation_reconciler,
        test_runner_public_key_pem=test_runner_public_key_pem,
        attestation_issuer=test_runner_issuer,
        release_signer_public_key_pem=release_signer_public_key_pem,
        trusted_issuer=release_issuer,
        release_id=plan.release_id,
        run_id=plan.run_id,
        branch=plan.branch,
        environment=plan.environment,
        source_commit=plan.source_commit,
        image_digest=plan.image_digest,
        source_digest=plan.source_digest,
        target_digest=plan.target_digest,
        attestation_token=attestation_token,
        artifact_receipt=attestation_receipt,
        now=now,
    )
    try:
        confirmed = await manifest_reconciler.reconcile(
            receipt=written,
            manifest_token=manifest_token,
            release_signer_public_key_pem=release_signer_public_key_pem,
            trusted_issuer=release_issuer,
            release_id=plan.release_id,
            run_id=plan.run_id,
            branch=plan.branch,
            environment=plan.environment,
            source_commit=plan.source_commit,
            image_digest=plan.image_digest,
            source_digest=plan.source_digest,
            target_digest=plan.target_digest,
            attestation_token=attestation_token,
            artifact_receipt=attestation_receipt,
            now=now,
        )
    except Exception as exc:
        raise EvidencePublicationUnconfirmed(
            "locked manifest written but exact-version readback unconfirmed"
        ) from exc
    if confirmed != written:
        raise EvidencePublicationUnconfirmed(
            "locked manifest receipt differs from readback"
        )
    return written
