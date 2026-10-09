"""Trusted Jenkins JUnit index custody fails closed on missing/foreign receipts."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.platform_runtime.aws_immutable_jenkins_junit_store import JenkinsJunitReceipt
from northstar_api.modules.platform_runtime.aws_jenkins_junit_evidence_index import JenkinsJunitIndexReceipt
from northstar_api.modules.platform_runtime.queue_notification_junit_index_custody import (
    JunitCustodyRejected,
    stage_witnessed_junit_custody,
    verify_custodied_junit_evidence,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
RELEASE = "release-123456"
RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
BUCKET = "northstar-qualification-evidence"
NAMES = ("notification_worker", "notification_egress", "notification_secrets")


def case():
    index_receipt = JenkinsJunitIndexReceipt(
        BUCKET, f"evidence/{RELEASE}/jenkins/{RUN}/junit/verified-index.json",
        "index-version-123", "d" * 64,
    )
    receipts = {
        name: JenkinsJunitReceipt(
            BUCKET, f"evidence/{RELEASE}/jenkins/{RUN}/junit/{name}.xml",
            f"{name}-version-123", "a" * 64,
        )
        for name in NAMES
    }
    proven = SimpleNamespace(
        run_id=RUN, branch=BRANCH, environment="staging",
        source_commit="c" * 40, source_digest="a" * 64,
        target_digest="b" * 64, witness_sha256="e" * 64,
    )
    identity = SimpleNamespace(verify=AsyncMock(return_value=True))
    index = SimpleNamespace(reconcile=AsyncMock(return_value=proven))
    reporter = SimpleNamespace(reconcile=AsyncMock())
    session = MagicMock()
    session.get = AsyncMock()
    session.flush = AsyncMock()
    arguments = dict(
        index=index, report_reconciler=reporter,
        release_id=RELEASE, run_id=RUN, branch=BRANCH,
        environment="staging", source_commit="c" * 40,
        source_digest="a" * 64, target_digest="b" * 64,
        witness_token="signed.witness", witness_public_key_pem=b"witness",
        attestation_signer_public_key_pem=b"signer", witness_issuer="witness-issuer",
        controller_id="jenkins-controller", job_full_name="Northstar/Tests",
        now=NOW,
    )
    return session, index, identity, index_receipt, receipts, proven, arguments


@pytest.mark.asyncio
async def test_valid_original_receipts_staged_without_commit_or_sign():
    session, index, identity, original, reports, proven, args = case()
    await stage_witnessed_junit_custody(
        session, identity=identity, index_receipt=original, receipts=reports, **args,
    )
    identity.verify.assert_awaited_once_with(run_id=RUN, branch=BRANCH)
    index.reconcile.assert_awaited_once()
    row = session.add.call_args.args[0]
    assert row.release_id == RELEASE
    assert row.run_id == RUN
    assert row.index_version_id == "index-version-123"
    assert row.witness_sha256 == proven.witness_sha256
    assert row.worker_version_id == reports["notification_worker"].version_id
    assert row.egress_sha256 == reports["notification_egress"].sha256
    assert row.secrets_key == reports["notification_secrets"].key
    session.flush.assert_awaited_once()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_identity_rejected_before_s3_and_database():
    session, index, identity, original, receipts, _proven, args = case()
    identity.verify.return_value = False
    with pytest.raises(PermissionError):
        await stage_witnessed_junit_custody(
            session, identity=identity, index_receipt=original, receipts=receipts, **args,
        )
    index.reconcile.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_s3_integrity_failure_blocks_database_insert():
    session, index, identity, original, receipts, _proven, args = case()
    index.reconcile.side_effect = ValueError("missing original S3 version")
    with pytest.raises(ValueError, match="original"):
        await stage_witnessed_junit_custody(
            session, identity=identity, index_receipt=original, receipts=receipts, **args,
        )
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_mismatched_provenance_blocks_custody():
    session, index, identity, original, receipts, proven, args = case()
    proven.source_commit = "f" * 40
    with pytest.raises(JunitCustodyRejected):
        await stage_witnessed_junit_custody(
            session, identity=identity, index_receipt=original, receipts=receipts, **args,
        )
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_foreign_receipt_bucket_blocks_custody():
    session, index, identity, original, receipts, _proven, args = case()
    item = receipts["notification_egress"]
    receipts["notification_egress"] = JenkinsJunitReceipt(
        "foreign-bucket", item.key, item.version_id, item.sha256,
    )
    with pytest.raises(JunitCustodyRejected):
        await stage_witnessed_junit_custody(
            session, identity=identity, index_receipt=original, receipts=receipts, **args,
        )
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_db_conflict_never_commits_or_overwrites():
    session, index, identity, original, receipts, _proven, args = case()
    session.flush.side_effect = RuntimeError("unique constraint violation")
    with pytest.raises(RuntimeError, match="unique constraint"):
        await stage_witnessed_junit_custody(
            session, identity=identity, index_receipt=original, receipts=receipts, **args,
        )
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_read_path_uses_database_original_receipts_not_caller_supplied():
    session, index, _identity, original, receipts, proven, args = case()
    row = SimpleNamespace(
        release_id=RELEASE, run_id=RUN, branch=BRANCH,
        environment="staging", source_commit="c" * 40,
        source_digest="a" * 64, target_digest="b" * 64,
        witness_sha256=proven.witness_sha256,
        index_bucket=original.bucket, index_key=original.key,
        index_version_id=original.version_id, index_sha256=original.sha256,
        worker_bucket=receipts["notification_worker"].bucket,
        worker_key=receipts["notification_worker"].key,
        worker_version_id=receipts["notification_worker"].version_id,
        worker_sha256=receipts["notification_worker"].sha256,
        egress_bucket=receipts["notification_egress"].bucket,
        egress_key=receipts["notification_egress"].key,
        egress_version_id=receipts["notification_egress"].version_id,
        egress_sha256=receipts["notification_egress"].sha256,
        secrets_bucket=receipts["notification_secrets"].bucket,
        secrets_key=receipts["notification_secrets"].key,
        secrets_version_id=receipts["notification_secrets"].version_id,
        secrets_sha256=receipts["notification_secrets"].sha256,
    )
    session.get.return_value = row
    value = await verify_custodied_junit_evidence(session, **args)
    assert value == proven
    session.get.assert_awaited_once()
    pinned = index.reconcile.await_args.kwargs
    assert pinned["index_receipt"] == original
    assert pinned["receipts"]["notification_egress"] == receipts["notification_egress"]
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_missing_or_cross_run_custody_denies_before_s3():
    session, index, _identity, original, receipts, proven, args = case()
    session.get.return_value = None
    with pytest.raises(JunitCustodyRejected):
        await verify_custodied_junit_evidence(session, **args)
    index.reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_saved_witness_digest_mismatch_denied():
    session, index, _identity, original, receipts, proven, args = case()
    session.get.return_value = SimpleNamespace(
        release_id=RELEASE, run_id=RUN, branch=BRANCH, environment="staging",
        source_commit="c" * 40, source_digest="a" * 64, target_digest="b" * 64,
        witness_sha256="0" * 64,
        index_bucket=original.bucket, index_key=original.key,
        index_version_id=original.version_id, index_sha256=original.sha256,
        worker_bucket=receipts["notification_worker"].bucket,
        worker_key=receipts["notification_worker"].key,
        worker_version_id=receipts["notification_worker"].version_id,
        worker_sha256=receipts["notification_worker"].sha256,
        egress_bucket=receipts["notification_egress"].bucket,
        egress_key=receipts["notification_egress"].key,
        egress_version_id=receipts["notification_egress"].version_id,
        egress_sha256=receipts["notification_egress"].sha256,
        secrets_bucket=receipts["notification_secrets"].bucket,
        secrets_key=receipts["notification_secrets"].key,
        secrets_version_id=receipts["notification_secrets"].version_id,
        secrets_sha256=receipts["notification_secrets"].sha256,
    )
    with pytest.raises(JunitCustodyRejected, match="witness"):
        await verify_custodied_junit_evidence(session, **args)
