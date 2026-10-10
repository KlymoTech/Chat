"""Jenkins release qualification requires immutable, readback-verified evidence."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.platform_runtime import queue_notification_release_link as linking
from northstar_api.modules.platform_runtime.aws_immutable_certification_artifact_store import (
    CertificationArtifactReceipt,
)
from northstar_api.modules.platform_runtime.aws_immutable_release_manifest_store import (
    ImmutableReleaseManifestReceipt,
)
from northstar_api.modules.platform_runtime.queue_notification_release_link import (
    QualificationReleaseLinkRejected,
    stage_qualification_release_link,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
RUN = "jenkins-build-123"
ID = f"jenkins:{RUN}"
ISSUER = "independent-test-runner"
SOURCE = "a" * 64
TARGET = "b" * 64


def harness():
    attestation = CertificationArtifactReceipt(
        "northstar-qualified-evidence",
        f"evidence/release-123456/jenkins/{RUN}/certification-attestation.token",
        "attestation-version", "f" * 64,
    )
    manifest = ImmutableReleaseManifestReceipt(
        "northstar-qualified-evidence",
        "evidence/release-123456/release-manifest.json",
        "manifest-version", "e" * 64,
    )
    verifier = SimpleNamespace(reconcile=AsyncMock(return_value=attestation))
    stored = SimpleNamespace(reconcile=AsyncMock(return_value=manifest))
    row = SimpleNamespace(
        approved=False, revoked=False, revision=1,
        issued_by=f"jenkins:{ISSUER}", environment="staging",
        source_digest=SOURCE, target_digest=TARGET,
        proof_tokens=["p1", "p2", "p3"],
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=row)
    session.flush = AsyncMock()
    expected = dict(
        authorized_publisher=True,
        qualification_id=ID,
        manifest_receipt=manifest,
        manifest_reconciler=stored,
        attestation_reconciler=verifier,
        manifest_token="signed.release",
        release_signer_public_key_pem=b"pinned-release-key",
        release_issuer="protected-release-issuer",
        test_runner_public_key_pem=b"pinned-test-key",
        attestation_issuer=ISSUER,
        attestation_token="signed.attestation",
        attestation_receipt=attestation,
        release_id="release-123456", run_id=RUN,
        branch="feature/northstar-adaptive-architecture-20261008",
        environment="staging",
        source_commit="c" * 40, image_digest="sha256:" + "d" * 64,
        source_digest=SOURCE, target_digest=TARGET, now=NOW,
    )
    verified = SimpleNamespace(
        release_id="release-123456", environment="staging",
        source_commit="c" * 40, image_digest="sha256:" + "d" * 64,
        manifest_sha256="1" * 64,
    )
    return session, row, expected, verified


@pytest.mark.asyncio
async def test_verified_release_link_is_pending_and_not_committed(monkeypatch):
    session, row, expected, verified = harness()
    check = AsyncMock(return_value=verified)
    monkeypatch.setattr(linking, "verify_manifest_and_reconcile_artifact", check)
    assert await stage_qualification_release_link(session, **expected) == ID
    check.assert_awaited_once()
    expected["manifest_reconciler"].reconcile.assert_awaited_once()
    expected["attestation_reconciler"].reconcile.assert_not_awaited()
    session.get.assert_awaited_once()
    assert session.get.await_args.kwargs["with_for_update"] is True
    link = session.add.call_args.args[0]
    assert link.qualification_id == ID
    assert link.release_id == verified.release_id
    assert link.manifest_version_id == "manifest-version"
    assert link.attestation_version_id == "attestation-version"
    assert link.signed_manifest_sha256 == verified.manifest_sha256
    assert row.approved is False
    session.flush.assert_awaited_once()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_missing_authorization_and_bad_jenkins_id_do_not_touch_db(monkeypatch):
    session, _row, expected, verified = harness()
    check = AsyncMock(return_value=verified)
    monkeypatch.setattr(linking, "verify_manifest_and_reconcile_artifact", check)
    expected["authorized_publisher"] = False
    with pytest.raises(PermissionError):
        await stage_qualification_release_link(session, **expected)
    expected["authorized_publisher"] = True
    expected["qualification_id"] = "jenkins:other-run"
    with pytest.raises(QualificationReleaseLinkRejected):
        await stage_qualification_release_link(session, **expected)
    check.assert_not_awaited()
    session.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_attestation_failure_denies_manifest_and_db(monkeypatch):
    session, _row, expected, _verified = harness()
    monkeypatch.setattr(
        linking, "verify_manifest_and_reconcile_artifact",
        AsyncMock(side_effect=ValueError("bad attestation")),
    )
    with pytest.raises(ValueError, match="bad attestation"):
        await stage_qualification_release_link(session, **expected)
    expected["manifest_reconciler"].reconcile.assert_not_awaited()
    session.get.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_manifest_readback_mismatch_denies_db(monkeypatch):
    session, _row, expected, verified = harness()
    monkeypatch.setattr(
        linking, "verify_manifest_and_reconcile_artifact",
        AsyncMock(return_value=verified),
    )
    expected["manifest_reconciler"].reconcile.return_value = None
    with pytest.raises(QualificationReleaseLinkRejected, match="version"):
        await stage_qualification_release_link(session, **expected)
    session.get.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"approved": True},
    {"revoked": True},
    {"revision": 2},
    {"issued_by": "another-issuer"},
    {"environment": "production"},
    {"source_digest": "f" * 64},
    {"target_digest": "f" * 64},
    {"proof_tokens": []},
])
async def test_wrong_pending_qualification_cannot_be_linked(monkeypatch, overrides):
    session, row, expected, verified = harness()
    for key, value in overrides.items():
        setattr(row, key, value)
    monkeypatch.setattr(
        linking, "verify_manifest_and_reconcile_artifact",
        AsyncMock(return_value=verified),
    )
    with pytest.raises(QualificationReleaseLinkRejected):
        await stage_qualification_release_link(session, **expected)
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_missing_qualification_cannot_be_linked(monkeypatch):
    session, _row, expected, verified = harness()
    session.get.return_value = None
    monkeypatch.setattr(
        linking, "verify_manifest_and_reconcile_artifact",
        AsyncMock(return_value=verified),
    )
    with pytest.raises(QualificationReleaseLinkRejected):
        await stage_qualification_release_link(session, **expected)
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_conflict_surfaces_without_commit(monkeypatch):
    session, _row, expected, verified = harness()
    session.flush.side_effect = RuntimeError("duplicate release")
    monkeypatch.setattr(
        linking, "verify_manifest_and_reconcile_artifact",
        AsyncMock(return_value=verified),
    )
    with pytest.raises(RuntimeError, match="duplicate release"):
        await stage_qualification_release_link(session, **expected)
    session.commit.assert_not_called()
