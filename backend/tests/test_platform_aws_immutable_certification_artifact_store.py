"""Signed, release-bound evidence is retained without allowing overwrite."""
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.aws_immutable_certification_artifact_store import (
    AwsImmutableCertificationArtifactStore,
    CertificationArtifactConflict,
    CertificationArtifactWriteUnknown,
)
from northstar_api.modules.platform_runtime.queue_notification_worker_qualification import (
    PersistedNotificationWorkerQualification,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
RUN = "jenkins-build-123"
RELEASE = "release-123456"
SOURCE = "a" * 64
TARGET = "b" * 64
COMMIT = "c" * 40
ISSUER = "northstar-isolated-test-runner"
BUCKET = "northstar-qualified-artifacts"
KMS = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
BRANCH = "feature/northstar-adaptive-architecture-20261008"


def evidence(private, *, changes=None):
    report = {
        "version": 1, "issuer": ISSUER, "run_id": RUN,
        "branch": BRANCH, "environment": "staging",
        "source_commit": COMMIT, "source_digest": SOURCE,
        "target_digest": TARGET,
        "started_at": int((NOW - timedelta(minutes=5)).timestamp()),
        "finished_at": int((NOW - timedelta(seconds=10)).timestamp()),
        "suites": {
            name: {"status": "passed", "tests_run": 5, "tests_failed": 0, "tests_skipped": 0}
            for name in PersistedNotificationWorkerQualification.REQUIRED
        },
    }
    report.update(changes or {})
    raw = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encode = lambda content: base64.urlsafe_b64encode(content).rstrip(b"=").decode()
    token = encode(raw) + "." + encode(private.sign(raw))
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return token, public


def harness(*, response=None):
    client = MagicMock()
    client.put_object.return_value = {"VersionId": "locked-version-001"} if response is None else response
    store = AwsImmutableCertificationArtifactStore(
        bucket=BUCKET, region="us-east-1", account_id="123456789012",
        kms_key_arn=KMS, s3_client=client,
    )
    private = Ed25519PrivateKey.generate()
    token, public = evidence(private)
    kwargs = dict(
        release_id=RELEASE, attestation_token=token,
        test_runner_public_key_pem=public, issuer=ISSUER,
        run_id=RUN, branch=BRANCH, environment="staging",
        source_commit=COMMIT, source_digest=SOURCE,
        target_digest=TARGET, now=NOW,
    )
    return store, client, private, kwargs


@pytest.mark.asyncio
async def test_verified_token_is_written_once_with_object_lock_kms_and_checksum():
    store, client, _, args = harness()
    receipt = await store.archive_attestation(**args)
    params = client.put_object.call_args.kwargs
    body = args["attestation_token"].encode("ascii")
    assert receipt.bucket == BUCKET
    assert receipt.version_id == "locked-version-001"
    assert receipt.key == f"evidence/{RELEASE}/jenkins/{RUN}/certification-attestation.token"
    assert receipt.sha256 == hashlib.sha256(body).hexdigest()
    assert params["Body"] == body
    assert params["IfNoneMatch"] == "*"
    assert params["ObjectLockMode"] == "COMPLIANCE"
    assert params["ObjectLockRetainUntilDate"] >= NOW + timedelta(days=90)
    assert params["ServerSideEncryption"] == "aws:kms"
    assert params["SSEKMSKeyId"] == KMS
    assert base64.b64decode(params["ChecksumSHA256"]) == hashlib.sha256(body).digest()
    assert "signing" not in repr(params).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"branch": "main"},
    {"source_commit": "d" * 40},
    {"target_digest": "d" * 64},
    {"finished_at": 1},
])
async def test_invalid_result_never_reaches_s3(changes):
    store, client, private, args = harness()
    args["attestation_token"] = evidence(private, changes=changes)[0]
    with pytest.raises(ValueError):
        await store.archive_attestation(**args)
    client.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_tampered_token_never_reaches_s3():
    store, client, _, args = harness()
    args["attestation_token"] += "tampered"
    with pytest.raises(ValueError):
        await store.archive_attestation(**args)
    client.put_object.assert_not_called()


@pytest.mark.asyncio
async def test_existing_object_fails_instead_of_overwriting():
    store, client, _, args = harness()
    client.put_object.side_effect = ClientError(
        {"Error": {"Code": "PreconditionFailed", "Message": "already exists"}},
        "PutObject",
    )
    with pytest.raises(CertificationArtifactConflict):
        await store.archive_attestation(**args)
    assert client.put_object.call_args.kwargs["IfNoneMatch"] == "*"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, {"VersionId": ""}, {"VersionId": None}])
async def test_missing_version_id_is_unknown_outcome(response):
    store, _, _, args = harness(response=response)
    with pytest.raises(CertificationArtifactWriteUnknown):
        await store.archive_attestation(**args)


@pytest.mark.asyncio
async def test_network_error_is_unknown_outcome_not_automatic_retry():
    store, client, _, args = harness()
    client.put_object.side_effect = ConnectionError("injected storage failure")
    with pytest.raises(CertificationArtifactWriteUnknown):
        await store.archive_attestation(**args)
    assert client.put_object.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("release", ["../release", "a", "invalid/slash"])
async def test_unsafe_release_ids_never_reach_s3(release):
    store, client, _, args = harness()
    args["release_id"] = release
    with pytest.raises(ValueError):
        await store.archive_attestation(**args)
    client.put_object.assert_not_called()


def test_rejects_noncompliant_storage_configuration():
    config = dict(
        bucket=BUCKET, region="us-east-1", account_id="123456789012",
        kms_key_arn=KMS, s3_client=MagicMock(),
    )
    for mutation in (
        {"bucket": "../other"},
        {"kms_key_arn": KMS.replace("123456789012", "000000000000")},
        {"retention_days": 1},
        {"region": "bad"},
        {"timeout_seconds": 0},
    ):
        with pytest.raises(ValueError):
            AwsImmutableCertificationArtifactStore(**{**config, **mutation})
