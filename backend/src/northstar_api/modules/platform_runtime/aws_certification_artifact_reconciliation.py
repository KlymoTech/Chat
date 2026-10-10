"""Read-only, version-fenced reconciliation of immutable Jenkins attestations.

Never repairs by overwriting or deleting: missing, altered, or unverifiable
artifacts block certification until reviewed by an independent operator.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from .aws_immutable_certification_artifact_store import CertificationArtifactReceipt
from .queue_notification_certification_attestation import verify_jenkins_certification_result

_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TOKEN_BYTES = 16384


class CertificationArtifactNotFound(RuntimeError):
    """The exact release/run/version does not exist."""


class CertificationArtifactIntegrityError(RuntimeError):
    """Stored bytes or compliance metadata do not match expected evidence."""


class CertificationArtifactReadUnknown(RuntimeError):
    """Storage read failed; do not assume that an artifact exists or is absent."""


class ReadOnlyCertificationArtifactReconciler:
    def __init__(
        self, *, bucket: str, kms_key_arn: str, s3_client: Any,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not bucket or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            raise ValueError("invalid qualification artifact bucket")
        if not re.fullmatch(r"arn:(?:aws|aws-us-gov):kms:[a-z0-9-]+:\d{12}:key/[0-9a-fA-F-]{36}", kms_key_arn):
            raise ValueError("invalid qualification KMS key")
        if not 0 < timeout_seconds <= 30 or s3_client is None:
            raise ValueError("invalid qualification storage adapter")
        self._bucket = bucket
        self._kms = kms_key_arn
        self._client = s3_client
        self._timeout = timeout_seconds

    async def reconcile(
        self, *, receipt: CertificationArtifactReceipt,
        release_id: str, attestation_token: str,
        test_runner_public_key_pem: bytes, issuer: str, run_id: str,
        branch: str, environment: str, source_commit: str,
        source_digest: str, target_digest: str,
        now: datetime | None = None,
    ) -> CertificationArtifactReceipt:
        """Verify signed expected bytes and read back their exact locked S3 version.

        An ambiguous prior write is reconciled only with its original key,
        expected digest and receipt version. There is no blind retry path.
        """
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("timezone-aware verification time required")
        if not _RELEASE.fullmatch(release_id) or not _RUN.fullmatch(run_id):
            raise ValueError("invalid release or run identifier")
        key = f"evidence/{release_id}/jenkins/{run_id}/certification-attestation.token"
        if (
            receipt.bucket != self._bucket or receipt.key != key
            or not isinstance(receipt.version_id, str)
            or not 1 <= len(receipt.version_id) <= 255
            or not _DIGEST.fullmatch(receipt.sha256)
        ):
            raise CertificationArtifactIntegrityError("receipt does not match pinned release")
        verify_jenkins_certification_result(
            attestation_token,
            test_runner_public_key_pem=test_runner_public_key_pem,
            issuer=issuer, run_id=run_id, branch=branch,
            environment=environment, source_commit=source_commit,
            source_digest=source_digest, target_digest=target_digest,
            now=instant,
        )
        data = attestation_token.encode("ascii")
        if len(data) > _MAX_TOKEN_BYTES or hashlib.sha256(data).hexdigest() != receipt.sha256:
            raise CertificationArtifactIntegrityError("receipt checksum does not match signed evidence")
        lookup = {"Bucket": self._bucket, "Key": key, "VersionId": receipt.version_id}
        try:
            head = await asyncio.wait_for(
                asyncio.to_thread(self._client.head_object, **lookup), self._timeout
            )
            if (
                head.get("VersionId") != receipt.version_id
                or head.get("ServerSideEncryption") != "aws:kms"
                or head.get("SSEKMSKeyId") != self._kms
                or head.get("ObjectLockMode") != "COMPLIANCE"
                or not isinstance(head.get("ObjectLockRetainUntilDate"), datetime)
                or head["ObjectLockRetainUntilDate"].tzinfo is None
                or head["ObjectLockRetainUntilDate"] <= instant.astimezone(UTC)
                or head.get("ContentLength") != len(data)
                or head.get("Metadata", {}).get("sha256") != receipt.sha256
                or head.get("Metadata", {}).get("source-commit") != source_commit
                or head.get("Metadata", {}).get("run-id") != run_id
            ):
                raise CertificationArtifactIntegrityError("S3 immutability or provenance metadata not qualified")
            response = await asyncio.wait_for(
                asyncio.to_thread(self._client.get_object, **lookup), self._timeout
            )
            stream = response.get("Body")
            if response.get("VersionId") != receipt.version_id or stream is None:
                raise CertificationArtifactIntegrityError("S3 version could not be read safely")
            try:
                body = await asyncio.wait_for(
                    asyncio.to_thread(stream.read, _MAX_TOKEN_BYTES + 1), self._timeout
                )
            finally:
                stream.close()
            if not isinstance(body, bytes) or body != data:
                raise CertificationArtifactIntegrityError("S3 evidence bytes do not match signed attestation")
            return receipt
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"NoSuchKey", "NoSuchVersion", "NotFound", "404"}:
                raise CertificationArtifactNotFound("pinned artifact version not found") from exc
            raise CertificationArtifactReadUnknown("certification artifact read unavailable") from exc
        except CertificationArtifactIntegrityError:
            raise
        except Exception as exc:
            raise CertificationArtifactReadUnknown("certification artifact read outcome unknown") from exc
