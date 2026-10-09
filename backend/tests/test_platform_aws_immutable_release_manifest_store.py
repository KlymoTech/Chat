"""Manifest upload remains conditional, pinned and non-deploying."""
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from northstar_api.modules.platform_runtime import aws_immutable_release_manifest_store as mod
from northstar_api.modules.platform_runtime.aws_immutable_certification_artifact_store import (
    CertificationArtifactReceipt,
)
from northstar_api.modules.platform_runtime.aws_immutable_release_manifest_store import (
    AwsImmutableReleaseManifestStore,
    ReleaseManifestAlreadyExists,
    ReleaseManifestWriteUnknown,
)

BUCKET = "northstar-qualification-evidence"
KMS = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
RELEASE = "release-123456"
RUN = "jenkins-build-123"
SHA = "c" * 40
IMAGE = "sha256:" + "d" * 64


def fixture():
    s3 = MagicMock()
    s3.put_object.return_value = {"VersionId": "locked-v01"}
    store = AwsImmutableReleaseManifestStore(
        bucket=BUCKET, region="us-east-1", account_id="123456789012",
        kms_key_arn=KMS, s3_client=s3,
    )
    receipt = CertificationArtifactReceipt(
        bucket=BUCKET,
        key=f"evidence/{RELEASE}/jenkins/{RUN}/certification-attestation.token",
        version_id="attestation-v01", sha256="f" * 64,
    )
    kwargs = dict(
        manifest_token="signed.payload",
        reconciler=SimpleNamespace(reconcile=AsyncMock()),
        test_runner_public_key_pem=b"test-runner-public",
        attestation_issuer="independent-test-runner",
        release_signer_public_key_pem=b"release-public",
        trusted_issuer="protected-release-issuer", release_id=RELEASE,
        run_id=RUN, branch="feature/northstar-adaptive-architecture-20261008",
        environment="staging", source_commit=SHA, image_digest=IMAGE,
        source_digest="a" * 64, target_digest="b" * 64,
        attestation_token="signed.attestation", artifact_receipt=receipt, now=NOW,
    )
    return store, s3, kwargs


@pytest.mark.asyncio
async def test_compliance_immutable_manifest_upload(monkeypatch):
    verified = SimpleNamespace(
        release_id=RELEASE, source_commit=SHA, image_digest=IMAGE
    )
    checker = AsyncMock(return_value=verified)
    monkeypatch.setattr(mod, "verify_manifest_and_reconcile_artifact", checker)
    store, s3, kwargs = fixture()
    result = await store.archive_manifest(**kwargs)
    request = s3.put_object.call_args.kwargs
    assert result.bucket == BUCKET
    assert result.key == f"evidence/{RELEASE}/release-manifest.json"
    assert result.version_id == "locked-v01"
    assert request["IfNoneMatch"] == "*"
    assert request["ObjectLockMode"] == "COMPLIANCE"
    assert request["ServerSideEncryption"] == "aws:kms"
    assert request["SSEKMSKeyId"] == KMS
    assert request["ObjectLockRetainUntilDate"] >= NOW + timedelta(days=91)
    assert request["ContentType"] == "application/json"
    assert json.loads(request["Body"]) == {
        "format": "northstar.signed-release-manifest.v1",
        "signed_manifest": "signed.payload",
    }
    assert base64.b64decode(request["ChecksumSHA256"]) == hashlib.sha256(request["Body"]).digest()
    assert result.sha256 == hashlib.sha256(request["Body"]).hexdigest()
    assert request["Metadata"]["image-digest"] == IMAGE
    checker.assert_awaited_once()
    s3.put_object.assert_called_once()


@pytest.mark.asyncio
async def test_cross_bucket_receipt_rejected_before_any_io():
    store, s3, kwargs = fixture()
    receipt = kwargs["artifact_receipt"]
    kwargs["artifact_receipt"] = CertificationArtifactReceipt(
        "foreign-bucket", receipt.key, receipt.version_id, receipt.sha256
    )
    with pytest.raises(ValueError, match="pinned bucket"):
        await store.archive_manifest(**kwargs)
    s3.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_prior_verification_failure_blocks_storage(monkeypatch):
    store, s3, kwargs = fixture()
    verification = AsyncMock(side_effect=ValueError("signed manifest invalid"))
    monkeypatch.setattr(mod, "verify_manifest_and_reconcile_artifact", verification)
    with pytest.raises(ValueError, match="signed manifest invalid"):
        await store.archive_manifest(**kwargs)
    verification.assert_awaited_once()
    s3.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_missing_attestation_blocks_storage(monkeypatch):
    store, s3, kwargs = fixture()
    verification = AsyncMock(side_effect=RuntimeError("locked attestation not found"))
    monkeypatch.setattr(mod, "verify_manifest_and_reconcile_artifact", verification)
    with pytest.raises(RuntimeError, match="locked attestation not found"):
        await store.archive_manifest(**kwargs)
    s3.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_existing_manifest_is_conflict_without_retry(monkeypatch):
    store, s3, kwargs = fixture()
    monkeypatch.setattr(
        mod, "verify_manifest_and_reconcile_artifact",
        AsyncMock(return_value=SimpleNamespace(
            release_id=RELEASE, source_commit=SHA, image_digest=IMAGE
        )),
    )
    s3.put_object.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed"}}, "PutObject"
    )
    with pytest.raises(ReleaseManifestAlreadyExists):
        await store.archive_manifest(**kwargs)
    s3.put_object.assert_called_once()
    assert s3.put_object.call_args.kwargs["IfNoneMatch"] == "*"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    "ConditionalRequestConflict", "AccessDenied", "SlowDown"
])
async def test_other_s3_errors_do_not_trigger_retry(monkeypatch, error):
    store, s3, kwargs = fixture()
    monkeypatch.setattr(
        mod, "verify_manifest_and_reconcile_artifact",
        AsyncMock(return_value=SimpleNamespace(
            release_id=RELEASE, source_commit=SHA, image_digest=IMAGE
        )),
    )
    s3.put_object.side_effect = ClientError(
        {"Error": {"Code": error}}, "PutObject"
    )
    with pytest.raises(ReleaseManifestWriteUnknown):
        await store.archive_manifest(**kwargs)
    assert s3.put_object.call_count == 1


@pytest.mark.asyncio
async def test_network_error_is_unknown_not_retryable(monkeypatch):
    store, s3, kwargs = fixture()
    monkeypatch.setattr(
        mod, "verify_manifest_and_reconcile_artifact",
        AsyncMock(return_value=SimpleNamespace(
            release_id=RELEASE, source_commit=SHA, image_digest=IMAGE
        )),
    )
    s3.put_object.side_effect = ConnectionError("socket timeout")
    with pytest.raises(ReleaseManifestWriteUnknown):
        await store.archive_manifest(**kwargs)
    assert s3.put_object.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    {}, {"VersionId": ""}, {"VersionId": None},
    {"VersionId": "v", "ChecksumSHA256": "bad"},
])
async def test_unconfirmed_version_or_checksum_is_unknown(monkeypatch, response):
    store, s3, kwargs = fixture()
    monkeypatch.setattr(
        mod, "verify_manifest_and_reconcile_artifact",
        AsyncMock(return_value=SimpleNamespace(
            release_id=RELEASE, source_commit=SHA, image_digest=IMAGE
        )),
    )
    s3.put_object.return_value = response
    with pytest.raises(ReleaseManifestWriteUnknown):
        await store.archive_manifest(**kwargs)


@pytest.mark.asyncio
async def test_naive_clock_rejected():
    store, s3, kwargs = fixture()
    kwargs["now"] = datetime(2026, 10, 10)
    with pytest.raises(ValueError, match="timezone-aware"):
        await store.archive_manifest(**kwargs)
    s3.put_object.assert_not_called()


def test_invalid_config_rejected():
    original = dict(
        bucket=BUCKET, region="us-east-1", account_id="123456789012",
        kms_key_arn=KMS, s3_client=MagicMock(),
    )
    for wrong in (
        {"bucket": "../wrong"}, {"bucket": "127.0.0.1"},
        {"region": "other"}, {"account_id": "1234"},
        {"kms_key_arn": KMS.replace("123456789012", "999999999999")},
        {"retention_days": 1}, {"timeout_seconds": 0},
    ):
        with pytest.raises(ValueError):
            AwsImmutableReleaseManifestStore(**(original | wrong))


@pytest.mark.asyncio
async def test_real_signed_manifest_contract_and_readback_before_put():
    """Exercise the actual release verifier; mock only external S3 read-back."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    attestation = "independently-signed-attestation.test-token"
    receipt = CertificationArtifactReceipt(
        bucket=BUCKET,
        key=f"evidence/{RELEASE}/jenkins/{RUN}/certification-attestation.token",
        version_id="attestation-v01",
        sha256=hashlib.sha256(attestation.encode()).hexdigest(),
    )
    report = {
        "version": 1,
        "issuer": "protected-release-issuer",
        "release_id": RELEASE,
        "run_id": RUN,
        "branch": "feature/northstar-adaptive-architecture-20261008",
        "environment": "staging",
        "source_commit": SHA,
        "image_digest": IMAGE,
        "source_digest": "a" * 64,
        "target_digest": "b" * 64,
        "attestation_sha256": receipt.sha256,
        "issued_at": int((NOW - timedelta(seconds=10)).timestamp()),
        "artifact": {
            "bucket": receipt.bucket,
            "key": receipt.key,
            "version_id": receipt.version_id,
            "sha256": receipt.sha256,
        },
    }
    data = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    encode = lambda binary: base64.urlsafe_b64encode(binary).rstrip(b"=").decode()
    token = encode(data) + "." + encode(private.sign(data))
    s3 = MagicMock()
    s3.put_object.return_value = {"VersionId": "manifest-v02"}
    reconciler = SimpleNamespace(reconcile=AsyncMock(return_value=receipt))
    store = AwsImmutableReleaseManifestStore(
        bucket=BUCKET, region="us-east-1", account_id="123456789012",
        kms_key_arn=KMS, s3_client=s3,
    )
    result = await store.archive_manifest(
        manifest_token=token,
        reconciler=reconciler,
        test_runner_public_key_pem=b"pinned-test-runner",
        attestation_issuer="independent-test-runner",
        release_signer_public_key_pem=public,
        trusted_issuer="protected-release-issuer",
        release_id=RELEASE,
        run_id=RUN,
        branch=report["branch"],
        environment="staging",
        source_commit=SHA,
        image_digest=IMAGE,
        source_digest="a" * 64,
        target_digest="b" * 64,
        attestation_token=attestation,
        artifact_receipt=receipt,
        now=NOW,
    )
    assert result.version_id == "manifest-v02"
    reconciler.reconcile.assert_awaited_once()
    assert reconciler.reconcile.await_args.kwargs["receipt"] == receipt
    assert json.loads(s3.put_object.call_args.kwargs["Body"])["signed_manifest"] == token
