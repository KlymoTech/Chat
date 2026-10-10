"""Read-back verifies exact S3 version, immutability and signed byte provenance."""
import base64
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.aws_certification_artifact_reconciliation import (
    CertificationArtifactIntegrityError,
    CertificationArtifactNotFound,
    CertificationArtifactReadUnknown,
    ReadOnlyCertificationArtifactReconciler,
)
from northstar_api.modules.platform_runtime.aws_immutable_certification_artifact_store import CertificationArtifactReceipt

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
BUCKET = "northstar-qualified-artifacts"
KMS = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
RELEASE = "release-123456"
RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
COMMIT = "c" * 40
SOURCE = "a" * 64
TARGET = "b" * 64
ISSUER = "northstar-isolated-test-runner"


def signed(private):
    payload = {
        "version": 1, "issuer": ISSUER, "run_id": RUN,
        "branch": BRANCH, "environment": "staging",
        "source_commit": COMMIT, "source_digest": SOURCE,
        "target_digest": TARGET,
        "started_at": int((NOW - timedelta(minutes=5)).timestamp()),
        "finished_at": int((NOW - timedelta(seconds=5)).timestamp()),
        "suites": {
            k: {"status": "passed", "tests_run": 3, "tests_failed": 0, "tests_skipped": 0}
            for k in ("notification_worker", "notification_egress", "notification_secrets")
        },
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    b64 = lambda d: base64.urlsafe_b64encode(d).rstrip(b"=").decode()
    return b64(body) + "." + b64(private.sign(body))


def fixture():
    private = Ed25519PrivateKey.generate()
    token = signed(private)
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    receipt = CertificationArtifactReceipt(
        bucket=BUCKET,
        key=f"evidence/{RELEASE}/jenkins/{RUN}/certification-attestation.token",
        version_id="locked-v001", sha256=hashlib.sha256(token.encode()).hexdigest(),
    )
    head = {
        "VersionId": receipt.version_id, "ContentLength": len(token),
        "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": KMS,
        "ObjectLockMode": "COMPLIANCE",
        "ObjectLockRetainUntilDate": NOW + timedelta(days=90),
        "Metadata": {"sha256": receipt.sha256, "source-commit": COMMIT, "run-id": RUN},
    }
    s3 = MagicMock()
    s3.head_object.return_value = head
    s3.get_object.return_value = {"VersionId": receipt.version_id, "Body": io.BytesIO(token.encode())}
    service = ReadOnlyCertificationArtifactReconciler(
        bucket=BUCKET, kms_key_arn=KMS, s3_client=s3,
    )
    opts = dict(
        receipt=receipt, release_id=RELEASE, attestation_token=token,
        test_runner_public_key_pem=public, issuer=ISSUER, run_id=RUN,
        branch=BRANCH, environment="staging", source_commit=COMMIT,
        source_digest=SOURCE, target_digest=TARGET, now=NOW,
    )
    return service, s3, opts


@pytest.mark.asyncio
async def test_exact_version_and_protected_bytes_reconcile():
    service, s3, options = fixture()
    assert await service.reconcile(**options) == options["receipt"]
    expected = {"Bucket": BUCKET, "Key": options["receipt"].key, "VersionId": "locked-v001"}
    s3.head_object.assert_called_once_with(**expected)
    s3.get_object.assert_called_once_with(**expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("ObjectLockMode", "GOVERNANCE"),
    ("ObjectLockRetainUntilDate", NOW - timedelta(days=1)),
    ("SSEKMSKeyId", "other-key"),
    ("ServerSideEncryption", "AES256"),
    ("VersionId", "other-version"),
    ("ContentLength", 100000),
])
async def test_noncompliant_head_metadata_blocks_content_read(field, value):
    service, s3, options = fixture()
    s3.head_object.return_value[field] = value
    with pytest.raises(CertificationArtifactIntegrityError):
        await service.reconcile(**options)
    s3.get_object.assert_not_called()


@pytest.mark.asyncio
async def test_wrong_stored_bytes_are_rejected():
    service, s3, options = fixture()
    s3.get_object.return_value["Body"] = io.BytesIO(b"tampered bytes")
    with pytest.raises(CertificationArtifactIntegrityError):
        await service.reconcile(**options)


@pytest.mark.asyncio
async def test_wrong_receipt_version_or_release_is_rejected_before_s3():
    service, s3, options = fixture()
    options["release_id"] = "release-other123"
    with pytest.raises(CertificationArtifactIntegrityError):
        await service.reconcile(**options)
    s3.head_object.assert_not_called()


@pytest.mark.asyncio
async def test_tampered_signed_result_blocks_s3():
    service, s3, options = fixture()
    options["attestation_token"] += "changed"
    with pytest.raises(ValueError):
        await service.reconcile(**options)
    s3.head_object.assert_not_called()


@pytest.mark.asyncio
async def test_missing_specific_version_is_not_found():
    service, s3, options = fixture()
    s3.head_object.side_effect = ClientError({"Error": {"Code": "NoSuchVersion"}}, "HeadObject")
    with pytest.raises(CertificationArtifactNotFound):
        await service.reconcile(**options)
    s3.get_object.assert_not_called()


@pytest.mark.asyncio
async def test_storage_fault_does_not_imply_absence_or_trigger_rewrite():
    service, s3, options = fixture()
    s3.head_object.side_effect = ConnectionError("unreachable")
    with pytest.raises(CertificationArtifactReadUnknown):
        await service.reconcile(**options)
    s3.get_object.assert_not_called()
    s3.put_object.assert_not_called()
    s3.delete_object.assert_not_called()
