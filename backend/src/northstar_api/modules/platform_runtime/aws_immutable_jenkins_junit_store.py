"""Append-only S3 storage of independently witnessed Jenkins JUnit evidence.

All three test reports and the independent Ed25519 witness are verified
before the first write. This module is NOT a signing service, qualification
approval, public endpoint, or deployment gate. Unknown/partial S3 writes
require independent, version-fenced operator reconciliation, never retry.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .aws_jenkins_evidence_publisher import PublicationIdentity
from .queue_notification_jenkins_test_provenance import (
    VerifiedJenkinsProvenance,
    verify_witnessed_jenkins_reports,
)

_SUITES = ("notification_egress", "notification_secrets", "notification_worker")
_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")
_BUCKET = re.compile(r"(?=.{3,63}\Z)[a-z0-9][a-z0-9.-]*[a-z0-9]\Z")
_REGION = re.compile(r"[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+\Z")
_KMS = re.compile(
    r"arn:(aws|aws-us-gov):kms:([a-z0-9-]+):([0-9]{12}):key/[0-9a-fA-F-]{36}\Z"
)


@dataclass(frozen=True)
class JenkinsJunitReceipt:
    bucket: str
    key: str
    version_id: str
    sha256: str


@dataclass(frozen=True)
class ArchivedJenkinsJunitEvidence:
    provenance: VerifiedJenkinsProvenance
    receipts: tuple[tuple[str, JenkinsJunitReceipt], ...]


class JenkinsJunitArchiveConflict(RuntimeError):
    """An immutable JUnit key was already written; never overwrite it."""


class JenkinsJunitArchiveUnknown(RuntimeError):
    """Write was uncertain, incomplete, or did not confirm an S3 version."""


class AwsImmutableJenkinsJunitStore:
    """Only an isolated, externally authorized Jenkins evidence publisher uses this."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        account_id: str,
        kms_key_arn: str,
        s3_client: Any = None,
        retention_days: int = 90,
        timeout_seconds: float = 10.0,
    ) -> None:
        match = _KMS.fullmatch(kms_key_arn) if isinstance(kms_key_arn, str) else None
        if (
            not isinstance(bucket, str)
            or _BUCKET.fullmatch(bucket) is None
            or ".." in bucket
            or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+", bucket)
            or not isinstance(region, str)
            or _REGION.fullmatch(region) is None
            or not isinstance(account_id, str)
            or re.fullmatch(r"[0-9]{12}", account_id) is None
            or match is None
            or match.group(1) != ("aws-us-gov" if region.startswith("us-gov-") else "aws")
            or match.group(2) != region
            or match.group(3) != account_id
            or not isinstance(retention_days, int)
            or not 90 <= retention_days <= 3650
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("invalid pinned JUnit evidence storage configuration")
        self._bucket = bucket
        self._kms = kms_key_arn
        self._retention = retention_days
        self._timeout = timeout_seconds
        self._s3 = s3_client if s3_client is not None else boto3.client(
            "s3",
            region_name=region,
            config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
        )

    async def archive_witnessed_reports(
        self,
        *,
        identity: PublicationIdentity,
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
        junit_reports: Mapping[str, bytes],
        now: datetime | None = None,
    ) -> ArchivedJenkinsJunitEvidence:
        """Verify first, then conditionally archive all three immutable reports.

        The role check must run under the publisher's own short-lived AWS
        credentials. Source SHA, release and test coordinates must originate
        from a separate protected build plan, never a tenant/API request.
        """
        if not await identity.verify(run_id=run_id, branch=branch):
            raise PermissionError("protected Jenkins JUnit publisher identity required")
        if (
            not isinstance(release_id, str) or _RELEASE.fullmatch(release_id) is None
            or not isinstance(run_id, str) or _RUN.fullmatch(run_id) is None
        ):
            raise ValueError("invalid pinned Jenkins release identity")
        instant = now or datetime.now(UTC)
        proven = verify_witnessed_jenkins_reports(
            witness_token,
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
            junit_reports=junit_reports,
            now=instant,
        )
        # The witness verification enforces exact suite names, bounded bytes,
        # schema and run/build identity before any S3 operation.
        receipts: list[tuple[str, JenkinsJunitReceipt]] = []
        for suite in _SUITES:
            body = junit_reports[suite]
            digest = hashlib.sha256(body).digest()
            key = f"evidence/{release_id}/jenkins/{run_id}/junit/{suite}.xml"
            request = {
                "Bucket": self._bucket,
                "Key": key,
                "Body": body,
                "IfNoneMatch": "*",
                "ContentType": "application/xml",
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": self._kms,
                "ObjectLockMode": "COMPLIANCE",
                "ObjectLockRetainUntilDate": instant.astimezone(UTC) + timedelta(
                    days=self._retention + 1
                ),
                "ChecksumSHA256": base64.b64encode(digest).decode("ascii"),
                "Metadata": {
                    "sha256": digest.hex(),
                    "source-commit": source_commit,
                    "run-id": run_id,
                    "suite": suite,
                    "witness-sha256": proven.witness_sha256,
                },
            }
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(self._s3.put_object, **request),
                    timeout=self._timeout,
                )
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"PreconditionFailed", "412"}:
                    raise JenkinsJunitArchiveConflict(
                        "JUnit report exists; any preceding report writes remain immutable"
                    ) from exc
                raise JenkinsJunitArchiveUnknown(
                    "JUnit publication failed; prior reports may already be archived"
                ) from exc
            except Exception as exc:
                raise JenkinsJunitArchiveUnknown(
                    "JUnit write outcome unknown; do not retry or replace evidence"
                ) from exc
            if (
                not isinstance(response, dict)
                or not isinstance(response.get("VersionId"), str)
                or not response["VersionId"]
                or response.get("ChecksumSHA256", request["ChecksumSHA256"])
                != request["ChecksumSHA256"]
            ):
                raise JenkinsJunitArchiveUnknown("immutable JUnit version not confirmed")
            receipts.append((
                suite,
                JenkinsJunitReceipt(
                    bucket=self._bucket,
                    key=key,
                    version_id=response["VersionId"],
                    sha256=digest.hex(),
                ),
            ))
        return ArchivedJenkinsJunitEvidence(provenance=proven, receipts=tuple(receipts))
