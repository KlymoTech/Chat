"""Immutable, version-fenced evidence index for a witnessed Jenkins run.

The index contains one signed witness token and EXACTLY three original JUnit
object-version receipts. It may be published only after a read-only S3
reconciliation of every report and requires a protected AWS publisher
identity. It cannot mint signatures, approve releases or activate workers.

S3 has no multi-object transactions. Never retry an unknown write, replace
an existing index or infer success from an unversioned key.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .aws_immutable_jenkins_junit_store import JenkinsJunitReceipt
from .aws_jenkins_evidence_publisher import PublicationIdentity
from .queue_notification_jenkins_test_provenance import VerifiedJenkinsProvenance

_SUITES = ("notification_egress", "notification_secrets", "notification_worker")
_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")
_BUCKET = re.compile(r"(?=.{3,63}\Z)[a-z0-9][a-z0-9.-]*[a-z0-9]\Z")
_REGION = re.compile(r"[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+\Z")
_KMS = re.compile(
    r"arn:(aws|aws-us-gov):kms:([a-z0-9-]+):([0-9]{12}):key/[0-9a-fA-F-]{36}\Z"
)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 24000


class JunitIndexConflict(RuntimeError):
    """This release/run index already exists; never overwrite."""


class JunitIndexWriteUnknown(RuntimeError):
    """A publication result was ambiguous; do not retry blindly."""


class JunitIndexVersionMissing(RuntimeError):
    """The exact originally pinned S3 index object version is missing."""


class JunitIndexIntegrityError(RuntimeError):
    """Persisted index bytes or compliance metadata are not trustworthy."""


class JunitIndexReadUnknown(RuntimeError):
    """Index read outcome was indeterminate."""


@dataclass(frozen=True)
class JenkinsJunitIndexReceipt:
    bucket: str
    key: str
    version_id: str
    sha256: str


@dataclass(frozen=True)
class IndexedJenkinsJunitEvidence:
    receipt: JenkinsJunitIndexReceipt
    provenance: VerifiedJenkinsProvenance


class WitnessedReportReconciler(Protocol):
    async def reconcile(
        self, *, receipts: Mapping[str, JenkinsJunitReceipt],
        release_id: str, witness_token: str, witness_public_key_pem: bytes,
        attestation_signer_public_key_pem: bytes, witness_issuer: str,
        controller_id: str, job_full_name: str, run_id: str,
        branch: str, environment: str, source_commit: str,
        source_digest: str, target_digest: str,
        now: datetime | None = None,
    ) -> VerifiedJenkinsProvenance: ...


def _expected_index(
    *, bucket: str, release_id: str, run_id: str,
    branch: str, environment: str, source_commit: str,
    source_digest: str, target_digest: str, witness_token: str,
    provenance: VerifiedJenkinsProvenance,
    receipts: Mapping[str, JenkinsJunitReceipt],
) -> bytes:
    if (
        not isinstance(release_id, str) or _RELEASE.fullmatch(release_id) is None
        or not isinstance(run_id, str) or _RUN.fullmatch(run_id) is None
        or not isinstance(receipts, Mapping)
        or frozenset(receipts) != frozenset(_SUITES)
        or not isinstance(witness_token, str)
        or not 1 <= len(witness_token) <= 16384
        or not isinstance(provenance, VerifiedJenkinsProvenance)
        or provenance.run_id != run_id
        or provenance.branch != branch
        or provenance.environment != environment
        or provenance.source_commit != source_commit
        or provenance.source_digest != source_digest
        or provenance.target_digest != target_digest
        or not _SHA.fullmatch(provenance.witness_sha256)
    ):
        raise JunitIndexIntegrityError("JUnit witness or release coordinates mismatch")
    for suite in _SUITES:
        receipt = receipts[suite]
        if (
            not isinstance(receipt, JenkinsJunitReceipt)
            or receipt.bucket != bucket
            or receipt.key != f"evidence/{release_id}/jenkins/{run_id}/junit/{suite}.xml"
            or not isinstance(receipt.version_id, str)
            or not 1 <= len(receipt.version_id) <= 255
            or not isinstance(receipt.sha256, str)
            or _SHA.fullmatch(receipt.sha256) is None
        ):
            raise JunitIndexIntegrityError("original JUnit receipt is invalid")
    payload = {
        "version": 1,
        "release_id": release_id,
        "run_id": run_id,
        "branch": branch,
        "environment": environment,
        "source_commit": source_commit,
        "source_digest": source_digest,
        "target_digest": target_digest,
        "witness_token": witness_token,
        "witness_sha256": provenance.witness_sha256,
        "suites": {name: asdict(receipts[name]) for name in _SUITES},
    }
    data = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    if len(data) > _MAX_BYTES:
        raise JunitIndexIntegrityError("JUnit evidence index too large")
    return data


class AwsJenkinsJunitEvidenceIndex:
    """Write-once index and independent readback; no self-contained approval."""

    def __init__(
        self, *, bucket: str, region: str, account_id: str,
        kms_key_arn: str, s3_client: Any = None,
        retention_days: int = 90, timeout_seconds: float = 10.0,
    ) -> None:
        match = _KMS.fullmatch(kms_key_arn) if isinstance(kms_key_arn, str) else None
        if (
            not isinstance(bucket, str) or _BUCKET.fullmatch(bucket) is None
            or ".." in bucket
            or not isinstance(region, str) or _REGION.fullmatch(region) is None
            or not isinstance(account_id, str)
            or re.fullmatch(r"[0-9]{12}", account_id) is None
            or match is None
            or match.group(1) != ("aws-us-gov" if region.startswith("us-gov-") else "aws")
            or match.group(2) != region or match.group(3) != account_id
            or not isinstance(retention_days, int) or not 90 <= retention_days <= 3650
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("invalid immutable JUnit index configuration")
        self._bucket = bucket
        self._kms = kms_key_arn
        self._retention = retention_days
        self._timeout = timeout_seconds
        self._s3 = s3_client if s3_client is not None else boto3.client(
            "s3", region_name=region,
            config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
        )

    async def publish(
        self, *, identity: PublicationIdentity, report_reconciler: WitnessedReportReconciler,
        receipts: Mapping[str, JenkinsJunitReceipt],
        release_id: str, witness_token: str, witness_public_key_pem: bytes,
        attestation_signer_public_key_pem: bytes, witness_issuer: str,
        controller_id: str, job_full_name: str, run_id: str, branch: str,
        environment: str, source_commit: str, source_digest: str,
        target_digest: str, now: datetime | None = None,
    ) -> IndexedJenkinsJunitEvidence:
        """Reconcile all three original versions BEFORE one locked index PUT."""
        if not await identity.verify(run_id=run_id, branch=branch):
            raise PermissionError("protected Jenkins index publisher identity required")
        instant = now or datetime.now(UTC)
        verified = await report_reconciler.reconcile(
            receipts=receipts, release_id=release_id, witness_token=witness_token,
            witness_public_key_pem=witness_public_key_pem,
            attestation_signer_public_key_pem=attestation_signer_public_key_pem,
            witness_issuer=witness_issuer, controller_id=controller_id,
            job_full_name=job_full_name, run_id=run_id, branch=branch,
            environment=environment, source_commit=source_commit,
            source_digest=source_digest, target_digest=target_digest, now=instant,
        )
        body = _expected_index(
            bucket=self._bucket, receipts=receipts, provenance=verified,
            release_id=release_id, run_id=run_id, branch=branch,
            environment=environment, source_commit=source_commit,
            source_digest=source_digest, target_digest=target_digest,
            witness_token=witness_token,
        )
        digest = hashlib.sha256(body).digest()
        key = f"evidence/{release_id}/jenkins/{run_id}/junit/verified-index.json"
        request = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
            "IfNoneMatch": "*",
            "ContentType": "application/json",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self._kms,
            "ObjectLockMode": "COMPLIANCE",
            "ObjectLockRetainUntilDate": instant.astimezone(UTC)
            + timedelta(days=self._retention + 1),
            "ChecksumSHA256": base64.b64encode(digest).decode("ascii"),
            "Metadata": {
                "sha256": digest.hex(),
                "witness-sha256": verified.witness_sha256,
                "source-commit": source_commit,
                "run-id": run_id,
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
                raise JunitIndexConflict("JUnit evidence index already exists") from exc
            raise JunitIndexWriteUnknown("JUnit evidence index write unknown") from exc
        except Exception as exc:
            raise JunitIndexWriteUnknown("JUnit evidence index write unknown") from exc
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("VersionId"), str)
            or not response["VersionId"]
            or response.get("ChecksumSHA256", request["ChecksumSHA256"])
            != request["ChecksumSHA256"]
        ):
            raise JunitIndexWriteUnknown("locked JUnit index version unconfirmed")
        return IndexedJenkinsJunitEvidence(
            receipt=JenkinsJunitIndexReceipt(
                bucket=self._bucket, key=key,
                version_id=response["VersionId"], sha256=digest.hex(),
            ),
            provenance=verified,
        )

    async def reconcile(
        self, *, index_receipt: JenkinsJunitIndexReceipt,
        report_reconciler: WitnessedReportReconciler,
        receipts: Mapping[str, JenkinsJunitReceipt],
        release_id: str, witness_token: str, witness_public_key_pem: bytes,
        attestation_signer_public_key_pem: bytes, witness_issuer: str,
        controller_id: str, job_full_name: str, run_id: str, branch: str,
        environment: str, source_commit: str, source_digest: str,
        target_digest: str, now: datetime | None = None,
    ) -> VerifiedJenkinsProvenance:
        """Re-verify the original index S3 version and all its JUnit references.

        The index receipt and suite receipts are externally pinned and
        NEVER reconstructed from the index's own untrusted stored contents.
        """
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("timezone-aware reconciliation required")
        key = f"evidence/{release_id}/jenkins/{run_id}/junit/verified-index.json"
        if (
            not isinstance(index_receipt, JenkinsJunitIndexReceipt)
            or index_receipt.bucket != self._bucket
            or index_receipt.key != key
            or not isinstance(index_receipt.version_id, str)
            or not 1 <= len(index_receipt.version_id) <= 255
            or not isinstance(index_receipt.sha256, str)
            or _SHA.fullmatch(index_receipt.sha256) is None
        ):
            raise JunitIndexIntegrityError("index receipt does not match protected release")
        # Independent readback of each pinned JUnit version verifies both
        # the witness signature and the report bytes before accepting index.
        verified = await report_reconciler.reconcile(
            receipts=receipts, release_id=release_id, witness_token=witness_token,
            witness_public_key_pem=witness_public_key_pem,
            attestation_signer_public_key_pem=attestation_signer_public_key_pem,
            witness_issuer=witness_issuer, controller_id=controller_id,
            job_full_name=job_full_name, run_id=run_id, branch=branch,
            environment=environment, source_commit=source_commit,
            source_digest=source_digest, target_digest=target_digest, now=instant,
        )
        expected = _expected_index(
            bucket=self._bucket, receipts=receipts, provenance=verified,
            release_id=release_id, run_id=run_id, branch=branch,
            environment=environment, source_commit=source_commit,
            source_digest=source_digest, target_digest=target_digest,
            witness_token=witness_token,
        )
        if hashlib.sha256(expected).hexdigest() != index_receipt.sha256:
            raise JunitIndexIntegrityError("index checksum differs from pinned receipt")
        lookup = {
            "Bucket": self._bucket, "Key": key,
            "VersionId": index_receipt.version_id,
        }
        try:
            head = await asyncio.wait_for(
                asyncio.to_thread(self._s3.head_object, **lookup), timeout=self._timeout,
            )
            metadata = head.get("Metadata") if isinstance(head, dict) else None
            until = head.get("ObjectLockRetainUntilDate") if isinstance(head, dict) else None
            if (
                not isinstance(head, dict)
                or head.get("VersionId") != index_receipt.version_id
                or head.get("ContentLength") != len(expected)
                or head.get("ContentType") != "application/json"
                or head.get("ServerSideEncryption") != "aws:kms"
                or head.get("SSEKMSKeyId") != self._kms
                or head.get("ObjectLockMode") != "COMPLIANCE"
                or not isinstance(until, datetime)
                or until.tzinfo is None
                or until <= instant.astimezone(UTC)
                or not isinstance(metadata, dict)
                or metadata.get("sha256") != index_receipt.sha256
                or metadata.get("witness-sha256") != verified.witness_sha256
                or metadata.get("run-id") != run_id
                or metadata.get("source-commit") != source_commit
            ):
                raise JunitIndexIntegrityError("locked JUnit index metadata invalid")
            response = await asyncio.wait_for(
                asyncio.to_thread(self._s3.get_object, **lookup), timeout=self._timeout,
            )
            if not isinstance(response, dict) or response.get("VersionId") != index_receipt.version_id:
                raise JunitIndexIntegrityError("S3 returned another index version")
            stream = response.get("Body")
            if stream is None:
                raise JunitIndexIntegrityError("index S3 content missing")
            try:
                body = await asyncio.wait_for(
                    asyncio.to_thread(stream.read, _MAX_BYTES + 1),
                    timeout=self._timeout,
                )
            finally:
                stream.close()
            if not isinstance(body, bytes) or body != expected:
                raise JunitIndexIntegrityError("stored signed witness/receipts differ")
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"NoSuchKey", "NoSuchVersion", "NotFound", "404"}:
                raise JunitIndexVersionMissing("pinned index version missing") from exc
            raise JunitIndexReadUnknown("index S3 read unavailable") from exc
        except JunitIndexIntegrityError:
            raise
        except Exception as exc:
            raise JunitIndexReadUnknown("index S3 read outcome unknown") from exc
        return verified
