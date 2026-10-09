"""Pinned signed release-manifest S3 read-back never mutates stored evidence."""
import base64
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from northstar_api.modules.platform_runtime.aws_immutable_certification_artifact_store import (
    CertificationArtifactReceipt,
)
from northstar_api.modules.platform_runtime.aws_immutable_release_manifest_store import (
    ImmutableReleaseManifestReceipt,
)
from northstar_api.modules.platform_runtime.aws_release_manifest_reconciliation import (
    ReadOnlyReleaseManifestReconciler,
    ReleaseManifestIntegrityError,
    ReleaseManifestReadUnknown,
    ReleaseManifestVersionMissing,
)
from northstar_api.modules.platform_runtime.queue_notification_release_manifest import (
    ReleaseManifestRejected,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
BUCKET = "northstar-qualification-evidence"
KMS = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
RELEASE = "release-123456"
RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
COMMIT = "c" * 40
IMAGE = "sha256:" + "d" * 64
SOURCE = "a" * 64
TARGET = "b" * 64
ISSUER = "protected-release-issuer"
ATTESTATION = "independent-signed-attestation.token"


def _b64(binary):
    return base64.urlsafe_b64encode(binary).rstrip(b"=").decode("ascii")


def harness():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    attested = CertificationArtifactReceipt(
        bucket=BUCKET,
        key=f"evidence/{RELEASE}/jenkins/{RUN}/certification-attestation.token",
        version_id="attestation-v1",
        sha256=hashlib.sha256(ATTESTATION.encode()).hexdigest(),
    )
    report = {
        "version": 1, "issuer": ISSUER, "release_id": RELEASE,
        "run_id": RUN, "branch": BRANCH, "environment": "staging",
        "source_commit": COMMIT, "image_digest": IMAGE,
        "source_digest": SOURCE, "target_digest": TARGET,
        "attestation_sha256": attested.sha256,
        "issued_at": int((NOW - timedelta(seconds=10)).timestamp()),
        "artifact": {
            "bucket": BUCKET, "key": attested.key,
            "version_id": attested.version_id, "sha256": attested.sha256,
        },
    }
    signed = json.dumps(report, separators=(",", ":"), sort_keys=True).encode()
    token = _b64(signed) + "." + _b64(private.sign(signed))
    body = json.dumps(
        {"format": "northstar.signed-release-manifest.v1", "signed_manifest": token},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    manifest = ImmutableReleaseManifestReceipt(
        bucket=BUCKET, key=f"evidence/{RELEASE}/release-manifest.json",
        version_id="locked-manifest-v1", sha256=hashlib.sha256(body).hexdigest(),
    )
    s3 = MagicMock()
    s3.head_object.return_value = {
        "VersionId": manifest.version_id, "ContentLength": len(body),
        "ContentType": "application/json",
        "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": KMS,
        "ObjectLockMode": "COMPLIANCE",
        "ObjectLockRetainUntilDate": NOW + timedelta(days=90),
        "Metadata": {
            "sha256": manifest.sha256, "source-commit": COMMIT,
            "run-id": RUN, "image-digest": IMAGE,
            "attestation-sha256": attested.sha256,
        },
    }
    s3.get_object.return_value = {
        "VersionId": manifest.version_id, "Body": io.BytesIO(body),
    }
    reconciler = ReadOnlyReleaseManifestReconciler(
        bucket=BUCKET, kms_key_arn=KMS, s3_client=s3,
    )
    params = dict(
        receipt=manifest, manifest_token=token,
        release_signer_public_key_pem=public, trusted_issuer=ISSUER,
        release_id=RELEASE, run_id=RUN, branch=BRANCH,
        environment="staging", source_commit=COMMIT, image_digest=IMAGE,
        source_digest=SOURCE, target_digest=TARGET,
        attestation_token=ATTESTATION, artifact_receipt=attested, now=NOW,
    )
    return reconciler, s3, params


@pytest.mark.asyncio
async def test_exact_locked_s3_version_and_signed_bytes_reconcile():
    verifier, s3, params = harness()
    assert await verifier.reconcile(**params) == params["receipt"]
    request = {
        "Bucket": BUCKET,
        "Key": params["receipt"].key,
        "VersionId": params["receipt"].version_id,
    }
    s3.head_object.assert_called_once_with(**request)
    s3.get_object.assert_called_once_with(**request)
    assert s3.get_object.return_value["Body"].closed
    s3.put_object.assert_not_called()
    s3.delete_object.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,bad", [
    ("VersionId", "wrong-version"),
    ("ContentLength", -1),
    ("ContentType", "application/octet-stream"),
    ("ServerSideEncryption", "AES256"),
    ("SSEKMSKeyId", "foreign-key"),
    ("ObjectLockMode", "GOVERNANCE"),
    ("ObjectLockRetainUntilDate", NOW - timedelta(seconds=1)),
    ("ObjectLockRetainUntilDate", NOW.replace(tzinfo=None)),
])
async def test_unqualified_head_metadata_blocks_content_read(field, bad):
    verifier, s3, params = harness()
    s3.head_object.return_value[field] = bad
    with pytest.raises(ReleaseManifestIntegrityError):
        await verifier.reconcile(**params)
    s3.get_object.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,bad", [
    ("sha256", "f" * 64),
    ("source-commit", "e" * 40),
    ("run-id", "jenkins-other123"),
    ("image-digest", "sha256:" + "e" * 64),
    ("attestation-sha256", "e" * 64),
])
async def test_wrong_provenance_metadata_denied(field, bad):
    verifier, s3, params = harness()
    s3.head_object.return_value["Metadata"][field] = bad
    with pytest.raises(ReleaseManifestIntegrityError):
        await verifier.reconcile(**params)
    s3.get_object.assert_not_called()


@pytest.mark.asyncio
async def test_stored_bytes_changed_even_at_same_length_denied():
    verifier, s3, params = harness()
    original = s3.get_object.return_value["Body"].getvalue()
    s3.get_object.return_value["Body"] = io.BytesIO(original[:-1] + b"!")
    with pytest.raises(ReleaseManifestIntegrityError):
        await verifier.reconcile(**params)
    assert s3.get_object.return_value["Body"].closed


@pytest.mark.asyncio
async def test_s3_get_returning_another_version_denied_and_stream_closed():
    verifier, s3, params = harness()
    s3.get_object.return_value["VersionId"] = "wrong-version"
    with pytest.raises(ReleaseManifestIntegrityError):
        await verifier.reconcile(**params)
    assert s3.get_object.return_value["Body"].closed


@pytest.mark.asyncio
async def test_receipt_mismatch_denied_before_io():
    verifier, s3, params = harness()
    original = params["receipt"]
    params["receipt"] = ImmutableReleaseManifestReceipt(
        original.bucket, original.key, original.version_id, "f" * 64,
    )
    with pytest.raises(ReleaseManifestIntegrityError):
        await verifier.reconcile(**params)
    s3.head_object.assert_not_called()


@pytest.mark.asyncio
async def test_wrong_image_digest_denied_before_io():
    verifier, s3, params = harness()
    params["image_digest"] = "sha256:" + "f" * 64
    with pytest.raises(ReleaseManifestRejected):
        await verifier.reconcile(**params)
    s3.head_object.assert_not_called()


@pytest.mark.asyncio
async def test_tampered_signature_denied_before_io():
    verifier, s3, params = harness()
    params["manifest_token"] += "altered"
    with pytest.raises(ReleaseManifestRejected):
        await verifier.reconcile(**params)
    s3.head_object.assert_not_called()


@pytest.mark.asyncio
async def test_missing_pinned_version_is_not_success():
    verifier, s3, params = harness()
    s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchVersion"}}, "HeadObject",
    )
    with pytest.raises(ReleaseManifestVersionMissing):
        await verifier.reconcile(**params)
    s3.get_object.assert_not_called()


@pytest.mark.asyncio
async def test_ambiguous_aws_failure_is_unknown_without_rewrite():
    verifier, s3, params = harness()
    s3.head_object.side_effect = ConnectionError("network error")
    with pytest.raises(ReleaseManifestReadUnknown):
        await verifier.reconcile(**params)
    s3.get_object.assert_not_called()
    s3.put_object.assert_not_called()
    s3.delete_object.assert_not_called()


@pytest.mark.asyncio
async def test_get_failure_is_unknown_without_rewrite():
    verifier, s3, params = harness()
    s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}}, "GetObject",
    )
    with pytest.raises(ReleaseManifestReadUnknown):
        await verifier.reconcile(**params)
    s3.put_object.assert_not_called()


def test_invalid_configuration_rejected():
    original = dict(
        bucket=BUCKET, kms_key_arn=KMS, s3_client=MagicMock(),
    )
    for bad in (
        {"bucket": "bad/unsafe"},
        {"kms_key_arn": "unsafe"},
        {"s3_client": None},
        {"timeout_seconds": 0},
    ):
        with pytest.raises(ValueError):
            ReadOnlyReleaseManifestReconciler(**(original | bad))
