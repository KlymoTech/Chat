"""Read-only reconciliation of the release manifest's own locked S3 version.

The writer first stores a canonical JSON wrapper containing the signed release
manifest. This verifier checks those exact bytes, the pinned release plan,
object version, encryption and COMPLIANCE retention. It never writes, retries,
replaces or deletes objects and does not approve a release.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from .aws_immutable_certification_artifact_store import CertificationArtifactReceipt
from .aws_immutable_release_manifest_store import ImmutableReleaseManifestReceipt
from .queue_notification_release_manifest import verify_signed_release_manifest

_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_BUCKET = re.compile(r"(?=.{3,63}\Z)[a-z0-9][a-z0-9.-]*[a-z0-9]\Z")
_KMS = re.compile(
    r"arn:(?:aws|aws-us-gov):kms:[a-z0-9-]+:\d{12}:key/[0-9a-fA-F-]{36}\Z"
)
_MAX_WRAPPER_BYTES = 20000


class ReleaseManifestVersionMissing(RuntimeError):
    """The pinned S3 key/version is missing; do not infer success."""


class ReleaseManifestIntegrityError(RuntimeError):
    """Release evidence bytes or S3 compliance metadata failed verification."""


class ReleaseManifestReadUnknown(RuntimeError):
    """Could not establish S3 evidence state; do not retry by overwriting."""


class ReadOnlyReleaseManifestReconciler:
    def __init__(
        self, *, bucket: str, kms_key_arn: str, s3_client: Any,
        timeout_seconds: float = 10.0,
    ) -> None:
        if (
            not _BUCKET.fullmatch(bucket) or ".." in bucket
            or not _KMS.fullmatch(kms_key_arn)
            or s3_client is None or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("invalid pinned release-manifest storage configuration")
        self._bucket = bucket
        self._kms = kms_key_arn
        self._s3 = s3_client
        self._timeout = timeout_seconds

    async def reconcile(
        self, *, receipt: ImmutableReleaseManifestReceipt,
        manifest_token: str,
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
        """Verify external release coordinates and exact immutable object version.

        Only a caller holding the original versioned receipt may reconcile an
        ambiguous write. A conflict with a different version is not silently
        promoted to a successful publication.
        """
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            raise ValueError("timezone-aware verification time required")
        if not _RELEASE.fullmatch(release_id):
            raise ValueError("invalid release identifier")
        verified = verify_signed_release_manifest(
            manifest_token,
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
        key = f"evidence/{release_id}/release-manifest.json"
        if (
            receipt.bucket != self._bucket
            or receipt.bucket != artifact_receipt.bucket
            or receipt.key != key
            or not isinstance(receipt.version_id, str)
            or not 1 <= len(receipt.version_id) <= 255
            or not _SHA.fullmatch(receipt.sha256)
        ):
            raise ReleaseManifestIntegrityError("manifest receipt is not pinned to this release")

        expected = json.dumps(
            {"format": "northstar.signed-release-manifest.v1", "signed_manifest": manifest_token},
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
        if (
            len(expected) > _MAX_WRAPPER_BYTES
            or hashlib.sha256(expected).hexdigest() != receipt.sha256
        ):
            raise ReleaseManifestIntegrityError("manifest checksum does not match receipt")

        request = {"Bucket": self._bucket, "Key": key, "VersionId": receipt.version_id}
        try:
            head = await asyncio.wait_for(
                asyncio.to_thread(self._s3.head_object, **request), self._timeout
            )
            if not isinstance(head, dict) or (
                head.get("VersionId") != receipt.version_id
                or head.get("ContentLength") != len(expected)
                or head.get("ContentType") != "application/json"
                or head.get("ServerSideEncryption") != "aws:kms"
                or head.get("SSEKMSKeyId") != self._kms
                or head.get("ObjectLockMode") != "COMPLIANCE"
                or not isinstance(head.get("ObjectLockRetainUntilDate"), datetime)
                or head["ObjectLockRetainUntilDate"].tzinfo is None
                or head["ObjectLockRetainUntilDate"] <= instant.astimezone(UTC)
                or not isinstance(head.get("Metadata"), dict)
                or head["Metadata"].get("sha256") != receipt.sha256
                or head["Metadata"].get("source-commit") != verified.source_commit
                or head["Metadata"].get("run-id") != run_id
                or head["Metadata"].get("image-digest") != verified.image_digest
                or head["Metadata"].get("attestation-sha256") != artifact_receipt.sha256
            ):
                raise ReleaseManifestIntegrityError("locked manifest metadata verification failed")

            response = await asyncio.wait_for(
                asyncio.to_thread(self._s3.get_object, **request), self._timeout
            )
            if not isinstance(response, dict):
                raise ReleaseManifestIntegrityError("versioned S3 response unavailable")
            stream = response.get("Body")
            if stream is None:
                raise ReleaseManifestIntegrityError("manifest content is missing")
            try:
                if response.get("VersionId") != receipt.version_id:
                    raise ReleaseManifestIntegrityError("read returned a different object version")
                data = await asyncio.wait_for(
                    asyncio.to_thread(stream.read, _MAX_WRAPPER_BYTES + 1),
                    self._timeout,
                )
            finally:
                stream.close()
            if not isinstance(data, bytes) or data != expected:
                raise ReleaseManifestIntegrityError("stored release manifest differs from verified signed bytes")
            return receipt
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"NoSuchKey", "NoSuchVersion", "NotFound", "404"}:
                raise ReleaseManifestVersionMissing("manifest key or version not found") from exc
            raise ReleaseManifestReadUnknown("release manifest S3 read unavailable") from exc
        except ReleaseManifestIntegrityError:
            raise
        except Exception as exc:
            raise ReleaseManifestReadUnknown("release manifest S3 read outcome unknown") from exc
