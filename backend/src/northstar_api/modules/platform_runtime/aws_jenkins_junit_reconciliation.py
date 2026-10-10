"""Read-only, version-fenced S3 retrieval of witnessed Jenkins JUnit bytes.

Every receipt originates from a separately protected publication record and
must name exactly its release/run/suite key and original S3 object version.
Neither a bucket listing nor a latest-key read can establish qualification.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from typing import Any, Mapping

from botocore.exceptions import ClientError

from .aws_immutable_jenkins_junit_store import JenkinsJunitReceipt
from .queue_notification_jenkins_test_provenance import (
    VerifiedJenkinsProvenance,
    verify_witnessed_jenkins_reports,
)

_SUITES = ("notification_egress", "notification_secrets", "notification_worker")
_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_BUCKET = re.compile(r"(?=.{3,63}\Z)[a-z0-9][a-z0-9.-]*[a-z0-9]\Z")
_KMS = re.compile(
    r"arn:(?:aws|aws-us-gov):kms:[a-z0-9-]+:[0-9]{12}:key/[0-9a-fA-F-]{36}\Z"
)
_MAX_BYTES = 131072


class JenkinsJunitVersionMissing(RuntimeError):
    """The exact pinned evidence version cannot be found."""


class JenkinsJunitIntegrityError(RuntimeError):
    """An S3 version is present but does not match locked trusted evidence."""


class JenkinsJunitReadUnknown(RuntimeError):
    """S3 reading was indeterminate; do not infer success or absence."""


class ReadOnlyWitnessedJunitReconciler:
    def __init__(
        self, *, bucket: str, kms_key_arn: str, s3_client: Any,
        timeout_seconds: float = 10.0,
    ) -> None:
        if (
            not isinstance(bucket, str)
            or _BUCKET.fullmatch(bucket) is None
            or ".." in bucket
            or not isinstance(kms_key_arn, str)
            or _KMS.fullmatch(kms_key_arn) is None
            or s3_client is None
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("invalid trusted JUnit evidence reconciler configuration")
        self._bucket = bucket
        self._kms = kms_key_arn
        self._s3 = s3_client
        self._timeout = timeout_seconds

    async def reconcile(
        self,
        *,
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
    ) -> VerifiedJenkinsProvenance:
        """Check all original versions then verify the independent witness.

        The witness and receipts must come from separate trusted build and
        archival boundaries, not from an untrusted Jenkins parameter, client
        request, or the unverified object contents themselves.
        """
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("timezone-aware reconciliation required")
        if (
            not isinstance(release_id, str)
            or _RELEASE.fullmatch(release_id) is None
            or not isinstance(run_id, str)
            or _RUN.fullmatch(run_id) is None
            or not isinstance(receipts, Mapping)
            or frozenset(receipts) != frozenset(_SUITES)
            or not isinstance(witness_token, str)
            or len(witness_token) > 16384
        ):
            raise JenkinsJunitIntegrityError("JUnit evidence receipt set not pinned")
        for suite in _SUITES:
            receipt = receipts[suite]
            key = f"evidence/{release_id}/jenkins/{run_id}/junit/{suite}.xml"
            if (
                not isinstance(receipt, JenkinsJunitReceipt)
                or receipt.bucket != self._bucket
                or receipt.key != key
                or not isinstance(receipt.version_id, str)
                or not 1 <= len(receipt.version_id) <= 255
                or not isinstance(receipt.sha256, str)
                or _SHA.fullmatch(receipt.sha256) is None
            ):
                raise JenkinsJunitIntegrityError("JUnit receipt has unexpected release, suite or version")

        # Signed witness is an independent assertion of SHA-256 and suite
        # counts. Every S3 read remains pinned to the separately held receipt,
        # even if a witness is invalid; its signature is checked below.
        raw_reports: dict[str, bytes] = {}
        witness_hashes: dict[str, str] = {}
        for suite in _SUITES:
            receipt = receipts[suite]
            request = {
                "Bucket": self._bucket,
                "Key": receipt.key,
                "VersionId": receipt.version_id,
            }
            try:
                head = await asyncio.wait_for(
                    asyncio.to_thread(self._s3.head_object, **request),
                    timeout=self._timeout,
                )
                metadata = head.get("Metadata") if isinstance(head, dict) else None
                until = head.get("ObjectLockRetainUntilDate") if isinstance(head, dict) else None
                if (
                    not isinstance(head, dict)
                    or head.get("VersionId") != receipt.version_id
                    or not isinstance(head.get("ContentLength"), int)
                    or not 1 <= head["ContentLength"] <= _MAX_BYTES
                    or head.get("ContentType") != "application/xml"
                    or head.get("ServerSideEncryption") != "aws:kms"
                    or head.get("SSEKMSKeyId") != self._kms
                    or head.get("ObjectLockMode") != "COMPLIANCE"
                    or not isinstance(until, datetime)
                    or until.tzinfo is None
                    or until <= instant.astimezone(UTC)
                    or not isinstance(metadata, dict)
                    or metadata.get("sha256") != receipt.sha256
                    or metadata.get("source-commit") != source_commit
                    or metadata.get("run-id") != run_id
                    or metadata.get("suite") != suite
                    or not isinstance(metadata.get("witness-sha256"), str)
                    or _SHA.fullmatch(metadata["witness-sha256"]) is None
                ):
                    raise JenkinsJunitIntegrityError("JUnit object lock or provenance metadata invalid")

                response = await asyncio.wait_for(
                    asyncio.to_thread(self._s3.get_object, **request),
                    timeout=self._timeout,
                )
                if not isinstance(response, dict):
                    raise JenkinsJunitIntegrityError("versioned JUnit response unavailable")
                stream = response.get("Body")
                if stream is None:
                    raise JenkinsJunitIntegrityError("JUnit object body missing")
                try:
                    if response.get("VersionId") != receipt.version_id:
                        raise JenkinsJunitIntegrityError("JUnit read returned a different S3 version")
                    report = await asyncio.wait_for(
                        asyncio.to_thread(stream.read, _MAX_BYTES + 1),
                        timeout=self._timeout,
                    )
                finally:
                    stream.close()
                if (
                    not isinstance(report, bytes)
                    or len(report) != head["ContentLength"]
                    or hashlib.sha256(report).hexdigest() != receipt.sha256
                ):
                    raise JenkinsJunitIntegrityError("raw JUnit content differs from versioned receipt")
                raw_reports[suite] = report
                witness_hashes[suite] = metadata["witness-sha256"]
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"NoSuchKey", "NoSuchVersion", "NotFound", "404"}:
                    raise JenkinsJunitVersionMissing("pinned JUnit object version not found") from exc
                raise JenkinsJunitReadUnknown("JUnit S3 read unavailable") from exc
            except JenkinsJunitIntegrityError:
                raise
            except Exception as exc:
                raise JenkinsJunitReadUnknown("JUnit S3 read outcome unknown") from exc

        verified = verify_witnessed_jenkins_reports(
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
            junit_reports=raw_reports,
            now=instant,
        )
        # Check the independently pinned raw signed-witness hash, not just
        # attacker-controlled values in the S3 object metadata.
        if any(witness_hashes[suite] != verified.witness_sha256 for suite in _SUITES):
            raise JenkinsJunitIntegrityError("JUnit evidence belongs to a different witness")
        return verified

