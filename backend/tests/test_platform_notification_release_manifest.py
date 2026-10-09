"""Signed release manifests fence source, image, environment and S3 evidence."""
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.aws_immutable_certification_artifact_store import (
    CertificationArtifactReceipt,
)
from northstar_api.modules.platform_runtime.queue_notification_release_manifest import (
    ReleaseManifestRejected,
    verify_manifest_and_reconcile_artifact,
    verify_signed_release_manifest,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
RELEASE = "release-123456"
RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
ISSUER = "isolated-release-authority"
COMMIT = "c" * 40
IMAGE = "sha256:" + "d" * 64
SOURCE = "a" * 64
TARGET = "b" * 64
ATTESTATION = "independently-signed-attestation.test-token"


def _encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def harness():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    receipt = CertificationArtifactReceipt(
        bucket="northstar-qualification-evidence",
        key=f"evidence/{RELEASE}/jenkins/{RUN}/certification-attestation.token",
        version_id="locked-v0001",
        sha256=hashlib.sha256(ATTESTATION.encode()).hexdigest(),
    )
    document = {
        "version": 1,
        "issuer": ISSUER,
        "release_id": RELEASE,
        "run_id": RUN,
        "branch": BRANCH,
        "environment": "staging",
        "source_commit": COMMIT,
        "image_digest": IMAGE,
        "source_digest": SOURCE,
        "target_digest": TARGET,
        "attestation_sha256": receipt.sha256,
        "issued_at": int((NOW - timedelta(seconds=10)).timestamp()),
        "artifact": {
            "bucket": receipt.bucket,
            "key": receipt.key,
            "version_id": receipt.version_id,
            "sha256": receipt.sha256,
        },
    }
    expected = {
        "release_signer_public_key_pem": public,
        "trusted_issuer": ISSUER,
        "release_id": RELEASE,
        "run_id": RUN,
        "branch": BRANCH,
        "environment": "staging",
        "source_commit": COMMIT,
        "image_digest": IMAGE,
        "source_digest": SOURCE,
        "target_digest": TARGET,
        "attestation_token": ATTESTATION,
        "artifact_receipt": receipt,
        "now": NOW,
    }
    return private, document, expected


def sign(private, document):
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return _encode(raw) + "." + _encode(private.sign(raw))


def test_signed_manifest_binds_exact_release_image_and_receipt():
    private, document, expected = harness()
    result = verify_signed_release_manifest(sign(private, document), **expected)
    assert result.release_id == RELEASE
    assert result.image_digest == IMAGE
    assert result.source_commit == COMMIT
    assert result.environment == "staging"
    assert result.artifact == expected["artifact_receipt"]
    assert len(result.manifest_sha256) == 64


@pytest.mark.parametrize("change", [
    {"release_id": "release-other123"},
    {"run_id": "jenkins-other123"},
    {"branch": "main"},
    {"environment": "production"},
    {"source_commit": "e" * 40},
    {"image_digest": "sha256:" + "f" * 64},
    {"source_digest": "f" * 64},
    {"target_digest": "f" * 64},
    {"attestation_sha256": "f" * 64},
    {"issued_at": int((NOW + timedelta(seconds=1)).timestamp())},
    {"issued_at": int((NOW - timedelta(minutes=16)).timestamp())},
])
def test_other_release_coordinates_cannot_be_substituted(change):
    private, document, expected = harness()
    document.update(change)
    with pytest.raises(ReleaseManifestRejected):
        verify_signed_release_manifest(sign(private, document), **expected)


@pytest.mark.parametrize("field,value", [
    ("version_id", "other-locked-version"),
    ("bucket", "other-certification-bucket"),
    ("sha256", "f" * 64),
    ("key", f"evidence/release-other123/jenkins/{RUN}/certification-attestation.token"),
])
def test_changed_artifact_receipt_fails_closed(field, value):
    private, document, expected = harness()
    document["artifact"][field] = value
    with pytest.raises(ReleaseManifestRejected):
        verify_signed_release_manifest(sign(private, document), **expected)


def test_expected_image_digest_must_come_from_protected_plan():
    private, document, expected = harness()
    expected["image_digest"] = "sha256:" + "f" * 64
    with pytest.raises(ReleaseManifestRejected):
        verify_signed_release_manifest(sign(private, document), **expected)


def test_unsigned_or_tampered_manifest_is_rejected():
    private, document, expected = harness()
    token = sign(private, document)
    another = sign(private, {**document, "environment": "production"})
    with pytest.raises(ReleaseManifestRejected):
        verify_signed_release_manifest(another.split(".")[0] + "." + token.split(".")[1], **expected)


def test_untrusted_signer_and_undocumented_fields_fail_closed():
    private, document, expected = harness()
    another = Ed25519PrivateKey.generate()
    with pytest.raises(ReleaseManifestRejected):
        verify_signed_release_manifest(sign(another, document), **expected)
    document["can_deploy"] = True
    with pytest.raises(ReleaseManifestRejected):
        verify_signed_release_manifest(sign(private, document), **expected)


def test_duplicate_signed_json_keys_are_rejected():
    private, document, expected = harness()
    raw = json.dumps(document, separators=(",", ":")).encode()
    altered = raw[:-1] + b',"environment":"production"}'
    with pytest.raises(ReleaseManifestRejected):
        verify_signed_release_manifest(
            _encode(altered) + "." + _encode(private.sign(altered)), **expected
        )


@pytest.mark.asyncio
async def test_only_verified_manifest_reaches_read_only_s3_reconciler():
    private, document, expected = harness()
    reconciler = SimpleNamespace(reconcile=AsyncMock(return_value=expected["artifact_receipt"]))
    result = await verify_manifest_and_reconcile_artifact(
        sign(private, document),
        reconciler=reconciler,
        test_runner_public_key_pem=b"pinned-test-runner-key",
        attestation_issuer="isolated-test-runner",
        **expected,
    )
    assert result.artifact == expected["artifact_receipt"]
    reconciler.reconcile.assert_awaited_once()
    args = reconciler.reconcile.await_args.kwargs
    assert args["receipt"] == result.artifact
    assert args["source_commit"] == COMMIT
    assert args["test_runner_public_key_pem"] == b"pinned-test-runner-key"


@pytest.mark.asyncio
async def test_invalid_manifest_does_not_touch_s3():
    private, document, expected = harness()
    reconciler = SimpleNamespace(reconcile=AsyncMock())
    document["image_digest"] = "sha256:" + "f" * 64
    with pytest.raises(ReleaseManifestRejected):
        await verify_manifest_and_reconcile_artifact(
            sign(private, document),
            reconciler=reconciler,
            test_runner_public_key_pem=b"pinned",
            attestation_issuer="isolated-test-runner",
            **expected,
        )
    reconciler.reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconciliation_failure_blocks_verified_result():
    private, document, expected = harness()
    reconciler = SimpleNamespace(reconcile=AsyncMock(side_effect=RuntimeError("S3 unavailable")))
    with pytest.raises(RuntimeError, match="S3 unavailable"):
        await verify_manifest_and_reconcile_artifact(
            sign(private, document),
            reconciler=reconciler,
            test_runner_public_key_pem=b"pinned",
            attestation_issuer="isolated-test-runner",
            **expected,
        )
