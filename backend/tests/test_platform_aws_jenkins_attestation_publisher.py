"""A publisher cannot persist Jenkins test evidence without trusted provenance."""
import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.aws_immutable_certification_artifact_store import (
    CertificationArtifactReceipt,
)
from northstar_api.modules.platform_runtime.aws_jenkins_attestation_publisher import (
    AttestationPublicationUnconfirmed,
    publish_verified_jenkins_attestation,
)
from northstar_api.modules.platform_runtime.aws_jenkins_evidence_publisher import (
    ProtectedReleaseCoordinates,
)
from northstar_api.modules.platform_runtime.queue_notification_certification_attestation import (
    CertificationAttestationError,
)
from northstar_api.modules.platform_runtime.queue_notification_worker_qualification import (
    PersistedNotificationWorkerQualification,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
BRANCH = "feature/northstar-adaptive-architecture-20261008"
RUN = "jenkins-build-123"
RELEASE = "release-123456"
ISSUER = "northstar-isolated-test-runner"
SOURCE = "a" * 64
TARGET = "b" * 64
COMMIT = "c" * 40
IMAGE = "sha256:" + "d" * 64


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def scenario(*, report_changes=None):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    report = dict(
        version=1, issuer=ISSUER, run_id=RUN, branch=BRANCH,
        environment="staging", source_commit=COMMIT,
        source_digest=SOURCE, target_digest=TARGET,
        started_at=int((NOW - timedelta(minutes=3)).timestamp()),
        finished_at=int((NOW - timedelta(seconds=10)).timestamp()),
        suites={
            kind: dict(status="passed", tests_run=8, tests_failed=0, tests_skipped=0)
            for kind in PersistedNotificationWorkerQualification.REQUIRED
        },
    )
    report.update(report_changes or {})
    raw = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    token = _b64(raw) + "." + _b64(private.sign(raw))
    original = CertificationArtifactReceipt(
        bucket="northstar-qualified-artifacts",
        key=f"evidence/{RELEASE}/jenkins/{RUN}/certification-attestation.token",
        version_id="immutable-test-v01",
        sha256=hashlib.sha256(token.encode()).hexdigest(),
    )
    identity = SimpleNamespace(verify=AsyncMock(return_value=True))
    store = SimpleNamespace(archive_attestation=AsyncMock(return_value=original))
    reader = SimpleNamespace(reconcile=AsyncMock(return_value=original))
    kwargs = dict(
        identity=identity, attestation_store=store,
        attestation_reconciler=reader,
        plan=ProtectedReleaseCoordinates(
            release_id=RELEASE, run_id=RUN, branch=BRANCH,
            environment="staging", source_commit=COMMIT,
            image_digest=IMAGE, source_digest=SOURCE, target_digest=TARGET,
        ),
        attestation_token=token,
        test_runner_public_key_pem=public,
        test_runner_issuer=ISSUER, now=NOW,
    )
    return kwargs, original


@pytest.mark.asyncio
async def test_signed_passing_attestation_publishes_and_reads_exact_version():
    params, receipt = scenario()
    assert await publish_verified_jenkins_attestation(**params) == receipt
    params["identity"].verify.assert_awaited_once_with(run_id=RUN, branch=BRANCH)
    params["attestation_store"].archive_attestation.assert_awaited_once()
    assert params["attestation_store"].archive_attestation.await_args.kwargs["release_id"] == RELEASE
    params["attestation_reconciler"].reconcile.assert_awaited_once()
    assert params["attestation_reconciler"].reconcile.await_args.kwargs["receipt"] == receipt


@pytest.mark.asyncio
async def test_denied_iam_role_never_reads_or_writes_s3():
    params, _ = scenario()
    params["identity"].verify.return_value = False
    with pytest.raises(PermissionError, match="publisher identity"):
        await publish_verified_jenkins_attestation(**params)
    params["attestation_store"].archive_attestation.assert_not_awaited()
    params["attestation_reconciler"].reconcile.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"branch": "main"},
    {"run_id": "jenkins-other456"},
    {"environment": "production"},
    {"source_commit": "f" * 40},
    {"source_digest": "f" * 64},
    {"target_digest": "f" * 64},
    {"finished_at": int((NOW - timedelta(minutes=16)).timestamp())},
])
async def test_wrong_or_expired_signed_test_provenance_fails_before_s3(changes):
    params, _ = scenario(report_changes=changes)
    with pytest.raises(CertificationAttestationError):
        await publish_verified_jenkins_attestation(**params)
    params["attestation_store"].archive_attestation.assert_not_awaited()


@pytest.mark.asyncio
async def test_bad_signature_fails_before_s3():
    params, _ = scenario()
    _, sig = params["attestation_token"].split(".")
    altered, _ = scenario(report_changes={"environment": "production"})
    params["attestation_token"] = altered["attestation_token"].split(".")[0] + "." + sig
    with pytest.raises(CertificationAttestationError):
        await publish_verified_jenkins_attestation(**params)
    params["attestation_store"].archive_attestation.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_protected_release_coordinates_fail_before_s3():
    params, _ = scenario()
    params["plan"] = replace(params["plan"], source_commit="f" * 40)
    with pytest.raises(CertificationAttestationError):
        await publish_verified_jenkins_attestation(**params)
    params["attestation_store"].archive_attestation.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_digest_image_fails_before_s3():
    params, _ = scenario()
    params["plan"] = replace(params["plan"], image_digest="latest")
    with pytest.raises(CertificationAttestationError):
        await publish_verified_jenkins_attestation(**params)
    params["attestation_store"].archive_attestation.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_conflict_not_replayed_or_mislabeled_success():
    params, _ = scenario()
    params["attestation_store"].archive_attestation.side_effect = RuntimeError("S3 conflict")
    with pytest.raises(RuntimeError, match="S3 conflict"):
        await publish_verified_jenkins_attestation(**params)
    params["attestation_store"].archive_attestation.assert_awaited_once()
    params["attestation_reconciler"].reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_readback_outage_fails_closed_without_retry():
    params, _ = scenario()
    params["attestation_reconciler"].reconcile.side_effect = RuntimeError("AWS unavailable")
    with pytest.raises(AttestationPublicationUnconfirmed):
        await publish_verified_jenkins_attestation(**params)
    params["attestation_store"].archive_attestation.assert_awaited_once()
    params["attestation_reconciler"].reconcile.assert_awaited_once()


@pytest.mark.asyncio
async def test_different_s3_object_version_never_confirms():
    params, receipt = scenario()
    params["attestation_reconciler"].reconcile.return_value = replace(
        receipt, version_id="different-version",
    )
    with pytest.raises(AttestationPublicationUnconfirmed):
        await publish_verified_jenkins_attestation(**params)
    params["attestation_store"].archive_attestation.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_version_never_confirms():
    params, _ = scenario()
    params["attestation_reconciler"].reconcile.return_value = None
    with pytest.raises(AttestationPublicationUnconfirmed):
        await publish_verified_jenkins_attestation(**params)
