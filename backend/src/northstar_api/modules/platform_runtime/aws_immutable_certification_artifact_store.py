"""Append-only, compliance-retained S3 storage for signed Jenkins attestations.

No tenant-facing API or worker is wired here. The bucket must have S3 Object
Lock enabled and versioning configured externally. IAM/bucket policy must deny
delete and retention bypass; the adapter's request parameters alone cannot
constitute a production immutability guarantee.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .queue_notification_certification_attestation import verify_jenkins_certification_result

_BUCKET = re.compile(r"(?=.{3,63}\Z)[a-z0-9][a-z0-9.-]*[a-z0-9]\Z")
_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")
_REGION = re.compile(r"[a-z]{2}(?:-gov)?-[a-z]+-\d+\Z")
_KMS = re.compile(r"arn:(?:aws|aws-us-gov):kms:([a-z0-9-]+):(\d{12}):key/[0-9a-fA-F-]{36}\Z")


class CertificationArtifactConflict(RuntimeError):
    """This release/run already owns an artifact; never overwrite it."""


class CertificationArtifactWriteUnknown(RuntimeError):
    """An S3 request failed or its durable outcome could not be established."""


@dataclass(frozen=True)
class CertificationArtifactReceipt:
    bucket: str
    key: str
    version_id: str
    sha256: str


class AwsImmutableCertificationArtifactStore:
    def __init__(
        self, *,
        bucket: str,
        region: str,
        account_id: str,
        kms_key_arn: str,
        s3_client: Any = None,
        retention_days: int = 90,
        timeout_seconds: float = 10.0,
    ) -> None:
        match = _KMS.fullmatch(kms_key_arn)
        if (
            not _BUCKET.fullmatch(bucket) or ".." in bucket or re.fullmatch(r"\d+\.\d+\.\d+\.\d+", bucket)
            or not _REGION.fullmatch(region)
            or not re.fullmatch(r"\d{12}", account_id)
            or match is None or match.group(1) != region or match.group(2) != account_id
            or not 30 <= retention_days <= 3650
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("invalid immutable certification artifact configuration")
        self._bucket = bucket
        self._kms = kms_key_arn
        self._retention = retention_days
        self._timeout = timeout_seconds
        self._s3 = s3_client if s3_client is not None else boto3.client(
            "s3", region_name=region,
            config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
        )

    async def archive_attestation(
        self,
        *,
        release_id: str,
        attestation_token: str,
        test_runner_public_key_pem: bytes,
        issuer: str,
        run_id: str,
        branch: str,
        environment: str,
        source_commit: str,
        source_digest: str,
        target_digest: str,
        now: datetime | None = None,
    ) -> CertificationArtifactReceipt:
        """Write the signed result once, retaining the exact verified bytes.

        On network/timeout ambiguity callers must reconcile using a separately
        approved read-only check; never retry with overwrite or a new key.
        """
        if not _RELEASE.fullmatch(release_id) or not _RUN.fullmatch(run_id):
            raise ValueError("invalid immutable artifact identity")
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("timezone-aware timestamp required")
        verify_jenkins_certification_result(
            attestation_token,
            test_runner_public_key_pem=test_runner_public_key_pem,
            issuer=issuer, run_id=run_id, branch=branch,
            environment=environment, source_commit=source_commit,
            source_digest=source_digest, target_digest=target_digest, now=instant,
        )
        body = attestation_token.encode("ascii")
        checksum = hashlib.sha256(body).digest()
        key = f"evidence/{release_id}/jenkins/{run_id}/certification-attestation.token"
        args = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
            "IfNoneMatch": "*",
            "ContentType": "application/octet-stream",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self._kms,
            "ObjectLockMode": "COMPLIANCE",
            "ObjectLockRetainUntilDate": instant.astimezone(UTC) + timedelta(days=self._retention + 1),
            "ChecksumSHA256": base64.b64encode(checksum).decode("ascii"),
            "Metadata": {
                "sha256": checksum.hex(),
                "source-commit": source_commit,
                "run-id": run_id,
            },
        }
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._s3.put_object, **args), timeout=self._timeout
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"}:
                raise CertificationArtifactConflict("certification artifact already exists or conflicts") from exc
            raise CertificationArtifactWriteUnknown("certification artifact storage unavailable") from exc
        except Exception as exc:
            raise CertificationArtifactWriteUnknown("certification artifact write outcome unknown") from exc

        if not isinstance(response, dict) or not isinstance(response.get("VersionId"), str) or not response["VersionId"]:
            raise CertificationArtifactWriteUnknown("versioned immutable storage not confirmed")
        return CertificationArtifactReceipt(
            bucket=self._bucket, key=key, version_id=response["VersionId"],
            sha256=checksum.hex(),
        )
