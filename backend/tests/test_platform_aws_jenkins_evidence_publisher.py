"""Trusted Jenkins publisher gates immutable manifest writes and readback."""
import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.aws_immutable_certification_artifact_store import (
    CertificationArtifactReceipt,
)
from northstar_api.modules.platform_runtime.aws_immutable_release_manifest_store import (
    ImmutableReleaseManifestReceipt,
)
from northstar_api.modules.platform_runtime.aws_jenkins_evidence_publisher import (
    AwsJenkinsEvidencePublisherIdentity,
    EvidencePublicationUnconfirmed,
    ProtectedReleaseCoordinates,
    publish_verified_release_manifest,
)
from northstar_api.modules.platform_runtime.queue_notification_release_manifest import (
    ReleaseManifestRejected,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
ACCOUNT = "123456789012"
ROLE = "northstar-evidence-publisher"
RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
RELEASE = "release-123456"
SOURCE = "a" * 64
TARGET = "b" * 64
COMMIT = "c" * 40
IMAGE = "sha256:" + "d" * 64
ATTESTATION = "independent-signed.attestation"
ISSUER = "protected-release-authority"


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def scenario():
    private = Ed25519PrivateKey.generate()
    pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    receipt = CertificationArtifactReceipt(
        bucket="northstar-evidence-bucket",
        key=f"evidence/{RELEASE}/jenkins/{RUN}/certification-attestation.token",
        version_id="attestation-version-123", sha256=__import__("hashlib").sha256(
            ATTESTATION.encode()
        ).hexdigest(),
    )
    data = {
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
        "issued_at": int((NOW - timedelta(seconds=2)).timestamp()),
        "artifact": {
            "bucket": receipt.bucket, "key": receipt.key,
            "version_id": receipt.version_id, "sha256": receipt.sha256,
        },
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    token = b64(raw) + "." + b64(private.sign(raw))
    locked = ImmutableReleaseManifestReceipt(
        bucket=receipt.bucket,
        key=f"evidence/{RELEASE}/release-manifest.json",
        version_id="locked-manifest-version",
        sha256="e" * 64,
    )
    identity = SimpleNamespace(verify=AsyncMock(return_value=True))
    writer = SimpleNamespace(archive_manifest=AsyncMock(return_value=locked))
    reader = SimpleNamespace(reconcile=AsyncMock(return_value=locked))
    attestation_reader = SimpleNamespace(reconcile=AsyncMock(return_value=receipt))
    options = dict(
        identity=identity,
        manifest_store=writer,
        manifest_reconciler=reader,
        attestation_reconciler=attestation_reader,
        plan=ProtectedReleaseCoordinates(
            release_id=RELEASE, run_id=RUN, branch=BRANCH,
            environment="staging", source_commit=COMMIT, image_digest=IMAGE,
            source_digest=SOURCE, target_digest=TARGET,
        ),
        manifest_token=token,
        attestation_token=ATTESTATION,
        attestation_receipt=receipt,
        release_signer_public_key_pem=pem,
        release_issuer=ISSUER,
        test_runner_public_key_pem=b"independent-test-runner-public",
        test_runner_issuer="independent-test-runner",
        now=NOW,
    )
    return options


@pytest.mark.asyncio
async def test_publisher_requires_identity_then_signed_manifest_then_exact_readback():
    params = scenario()
    receipt = await publish_verified_release_manifest(**params)
    assert receipt.version_id == "locked-manifest-version"
    params["identity"].verify.assert_awaited_once_with(run_id=RUN, branch=BRANCH)
    params["manifest_store"].archive_manifest.assert_awaited_once()
    params["manifest_reconciler"].reconcile.assert_awaited_once()
    assert params["manifest_reconciler"].reconcile.await_args.kwargs["receipt"] == receipt


@pytest.mark.asyncio
async def test_rejected_machine_identity_never_reaches_storage():
    params = scenario()
    params["identity"].verify.return_value = False
    with pytest.raises(PermissionError):
        await publish_verified_release_manifest(**params)
    params["manifest_store"].archive_manifest.assert_not_awaited()
    params["manifest_reconciler"].reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_tampered_manifest_never_reaches_storage():
    params = scenario()
    params["manifest_token"] += "tampered"
    with pytest.raises(ReleaseManifestRejected):
        await publish_verified_release_manifest(**params)
    params["manifest_store"].archive_manifest.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_protected_image_never_reaches_storage():
    params = scenario()
    original = params["plan"]
    params["plan"] = ProtectedReleaseCoordinates(
        release_id=original.release_id, run_id=original.run_id,
        branch=original.branch, environment=original.environment,
        source_commit=original.source_commit, image_digest="sha256:" + "f" * 64,
        source_digest=original.source_digest, target_digest=original.target_digest,
    )
    with pytest.raises(ReleaseManifestRejected):
        await publish_verified_release_manifest(**params)
    params["manifest_store"].archive_manifest.assert_not_awaited()


@pytest.mark.asyncio
async def test_unconfirmed_s3_readback_blocks_publication_success():
    params = scenario()
    params["manifest_reconciler"].reconcile.return_value = None
    with pytest.raises(EvidencePublicationUnconfirmed):
        await publish_verified_release_manifest(**params)
    params["manifest_store"].archive_manifest.assert_awaited_once()


@pytest.mark.asyncio
async def test_readback_error_is_unknown_and_never_triggers_new_write():
    params = scenario()
    params["manifest_reconciler"].reconcile.side_effect = RuntimeError("AWS unavailable")
    with pytest.raises(EvidencePublicationUnconfirmed):
        await publish_verified_release_manifest(**params)
    params["manifest_store"].archive_manifest.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_failure_stops_before_readback():
    params = scenario()
    params["manifest_store"].archive_manifest.side_effect = RuntimeError("S3 precondition failed")
    with pytest.raises(RuntimeError, match="S3 precondition failed"):
        await publish_verified_release_manifest(**params)
    params["manifest_reconciler"].reconcile.assert_not_awaited()


def identity(sts):
    return AwsJenkinsEvidencePublisherIdentity(
        account_id=ACCOUNT, region="us-east-1", role_name=ROLE,
        allowed_branch=BRANCH, sts_client=sts,
    )


@pytest.mark.asyncio
async def test_exact_aws_account_role_and_run_session_required():
    sts = MagicMock()
    session = "northstar-evidence-" + RUN
    sts.get_caller_identity.return_value = {
        "Account": ACCOUNT,
        "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/{ROLE}/{session}",
        "UserId": "AROAEXAMPLE123:" + session,
    }
    assert await identity(sts).verify(run_id=RUN, branch=BRANCH) is True
    sts.get_caller_identity.assert_called_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"Account": "000000000000"},
    {"Arn": "arn:aws:sts::123456789012:assumed-role/untrusted/northstar-evidence-jenkins-build-123"},
    {"UserId": "AROAEXAMPLE123:another-build"},
])
async def test_wrong_aws_workload_identity_denied(change):
    sts = MagicMock()
    session = "northstar-evidence-" + RUN
    sts.get_caller_identity.return_value = {
        "Account": ACCOUNT,
        "Arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/{ROLE}/{session}",
        "UserId": "AROAEXAMPLE123:" + session,
        **change,
    }
    assert await identity(sts).verify(run_id=RUN, branch=BRANCH) is False


@pytest.mark.asyncio
async def test_wrong_branch_and_unsafe_run_never_contact_sts():
    sts = MagicMock()
    gate = identity(sts)
    assert await gate.verify(run_id=RUN, branch="main") is False
    assert await gate.verify(run_id="../../etc/passwd", branch=BRANCH) is False
    sts.get_caller_identity.assert_not_called()


@pytest.mark.asyncio
async def test_sts_failure_denied():
    sts = MagicMock()
    sts.get_caller_identity.side_effect = RuntimeError("AWS unavailable")
    assert await identity(sts).verify(run_id=RUN, branch=BRANCH) is False


@pytest.mark.parametrize("change", [
    {"account_id": "bad"},
    {"region": "bad"},
    {"role_name": "../nope"},
    {"allowed_branch": ""},
    {"timeout_seconds": 0},
])
def test_publisher_identity_configuration_fails_closed(change):
    base = dict(account_id=ACCOUNT, region="us-east-1", role_name=ROLE,
                allowed_branch=BRANCH, sts_client=MagicMock())
    with pytest.raises(ValueError):
        AwsJenkinsEvidencePublisherIdentity(**{**base, **change})
