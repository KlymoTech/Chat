"""Persist independently verified release manifests to versioned, locked S3.

This is a write-only boundary, not a release approval or worker activation.
The caller must provide release coordinates and signer keys from a separately
protected deployment plan. Bucket Object Lock, KMS and least-privilege IAM must
be provisioned and independently tested before any production publication.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .aws_immutable_certification_artifact_store import CertificationArtifactReceipt
from .queue_notification_release_manifest import (
    ArtifactReconciler,
    verify_manifest_and_reconcile_artifact,
)

_BUCKET = re.compile(r"(?=.{3,63}\Z)[a-z0-9][a-z0-9.-]*[a-z0-9]\Z")
_REGION = re.compile(r"[a-z]{2}(?:-gov)?-[a-z]+-\d+\Z")
_KMS = re.compile(r"arn:(?:aws|aws-us-gov):kms:([a-z0-9-]+):(\d{12}):key/[0-9a-fA-F-]{36}\Z")


class ReleaseManifestAlreadyExists(RuntimeError):
    """A manifest exists for this release; no overwrite is permitted."""


class ReleaseManifestWriteUnknown(RuntimeError):
    """S3 did not confirm a versioned, durable write; do not retry blindly."""


@dataclass(frozen=True)
class ImmutableReleaseManifestReceipt:
    bucket: str
    key: str
    version_id: str
    sha256: str


class AwsImmutableReleaseManifestStore:
    """Require attestation read-back before append-only manifest publication."""

    def __init__(
        self, *, bucket: str, region: str, account_id: str,
        kms_key_arn: str, s3_client: Any = None,
        retention_days: int = 90, timeout_seconds: float = 10.0,
    ) -> None:
        match = _KMS.fullmatch(kms_key_arn)
        if (
            not _BUCKET.fullmatch(bucket) or ".." in bucket
            or re.fullmatch(r"\d+\.\d+\.\d+\.\d+", bucket)
            or not _REGION.fullmatch(region)
            or not re.fullmatch(r"\d{12}", account_id)
            or match is None or match.group(1) != region or match.group(2) != account_id
            or not 30 <= retention_days <= 3650
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("invalid immutable release-manifest configuration")
        self._bucket = bucket
        self._kms_key_arn = kms_key_arn
        self._retention_days = retention_days
        self._timeout = timeout_seconds
        self._s3 = s3_client if s3_client is not None else boto3.client(
            "s3", region_name=region,
            config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
        )

    async def archive_manifest(
        self, *, manifest_token: str,
        reconciler: ArtifactReconciler,
        test_runner_public_key_pem: bytes,
        attestation_issuer: str,
        release_signer_public_key_pem: bytes,
        trusted_issuer: str,
        release_id: str,
        run_id: str,
        branch: str,
        environment: str,
        source_commit: str,
        image_digest: str,
        source_digest: str,
        target_digest: str,
        attestation_token: str,
        artifact_receipt: CertificationArtifactReceipt,
        now: datetime | None = None,
    ) -> ImmutableReleaseManifestReceipt:
        """Store canonical JSON wrapper with exact signed manifest token, once.

        Reject unverifiable signed evidence before S3 PUT. S3 failures or
        ambiguous timeouts require independent read-only reconciliation.
        """
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("timezone-aware timestamp required")
        if artifact_receipt.bucket != self._bucket:
            raise ValueError("release manifest and signed attestation must use pinned bucket")
        verified = await verify_manifest_and_reconcile_artifact(
            manifest_token,
            reconciler=reconciler,
            test_runner_public_key_pem=test_runner_public_key_pem,
            attestation_issuer=attestation_issuer,
            release_signer_public_key_pem=release_signer_public_key_pem,
            trusted_issuer=trusted_issuer,
            release_id=release_id,
            run_id=run_id,
            branch=branch,
            environment=environment,
            source_commit=source_commit,
            image_digest=image_digest,
            source_digest=source_digest,
            target_digest=target_digest,
            attestation_token=attestation_token,
            artifact_receipt=artifact_receipt,
            now=instant,
        )
        key = f"evidence/{verified.release_id}/release-manifest.json"
        body = json.dumps(
            {"format": "northstar.signed-release-manifest.v1", "signed_manifest": manifest_token},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
        digest = hashlib.sha256(body).digest()
        args = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
            "IfNoneMatch": "*",
            "ContentType": "application/json",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self._kms_key_arn,
            "ObjectLockMode": "COMPLIANCE",
            "ObjectLockRetainUntilDate": instant.astimezone(UTC) + timedelta(days=self._retention_days + 1),
            "ChecksumSHA256": base64.b64encode(digest).decode("ascii"),
            "Metadata": {
                "sha256": digest.hex(),
                "source-commit": verified.source_commit,
                "run-id": run_id,
                "image-digest": verified.image_digest,
                "attestation-sha256": artifact_receipt.sha256,
            },
        }
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._s3.put_object, **args), timeout=self._timeout
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"PreconditionFailed", "412"}:
                raise ReleaseManifestAlreadyExists("release manifest already exists") from exc
            raise ReleaseManifestWriteUnknown("release manifest write outcome unconfirmed") from exc
        except Exception as exc:
            raise ReleaseManifestWriteUnknown("release manifest write outcome unconfirmed") from exc

        if (
            not isinstance(response, dict)
            or not isinstance(response.get("VersionId"), str)
            or not response["VersionId"]
            or response.get("ChecksumSHA256", args["ChecksumSHA256"]) != args["ChecksumSHA256"]
        ):
            raise ReleaseManifestWriteUnknown("locked release-manifest version not confirmed")
        return ImmutableReleaseManifestReceipt(
            bucket=self._bucket,
            key=key,
            version_id=response["VersionId"],
            sha256=digest.hex(),
        )
