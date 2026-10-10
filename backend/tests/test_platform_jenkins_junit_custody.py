"""Only independently verified immutable S3 receipts enter DB custody."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, tzinfo
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.platform_runtime.aws_immutable_jenkins_junit_store import (
    JenkinsJunitReceipt,
)
from northstar_api.modules.platform_runtime.aws_jenkins_junit_evidence_index import (
    JenkinsJunitIndexReceipt,
)
from northstar_api.modules.platform_runtime.queue_notification_jenkins_junit_custody import (
    JenkinsJunitCustodyRejected,
    load_and_reconcile_witnessed_junit_custody,
    stage_witnessed_junit_custody,
)
from northstar_api.modules.platform_runtime.queue_notification_jenkins_junit_custody_persistence import (
    NotificationJenkinsJunitCustodyRecord,
)
from northstar_api.modules.platform_runtime.queue_notification_jenkins_test_provenance import (
    VerifiedJenkinsProvenance,
)

class NoOffsetTZ(tzinfo):
    def utcoffset(self, dt):
        return None


NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
RELEASE = "release-123456"
RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
BUCKET = "northstar-qualification-artifacts"
SUITES = ("notification_egress", "notification_secrets", "notification_worker")


def setup():
    proven = VerifiedJenkinsProvenance(
        run_id=RUN, branch=BRANCH, environment="staging",
        source_commit="c" * 40, source_digest="a" * 64,
        target_digest="b" * 64,
        started_at=int(NOW.timestamp()) - 180,
        finished_at=int(NOW.timestamp()) - 5,
        tests_run=tuple((suite, 1) for suite in SUITES),
        witness_sha256="f" * 64,
    )
    index_receipt = JenkinsJunitIndexReceipt(
        bucket=BUCKET,
        key=f"evidence/{RELEASE}/jenkins/{RUN}/junit/verified-index.json",
        version_id="locked-index-version-123",
        sha256="e" * 64,
    )
    receipts = {
        suite: JenkinsJunitReceipt(
            bucket=BUCKET,
            key=f"evidence/{RELEASE}/jenkins/{RUN}/junit/{suite}.xml",
            version_id=f"{suite}-version",
            sha256="d" * 64,
        )
        for suite in SUITES
    }
    session = MagicMock()
    session.flush = AsyncMock()
    session.get = AsyncMock()
    identity = SimpleNamespace(verify=AsyncMock(return_value=True))
    verifier = SimpleNamespace(reconcile=AsyncMock(return_value=proven))
    report_reconciler = SimpleNamespace(reconcile=AsyncMock())
    options = dict(
        identity=identity, session=session,
        index_reconciler=verifier,
        report_reconciler=report_reconciler,
        index_receipt=index_receipt, receipts=receipts,
        release_id=RELEASE, run_id=RUN, branch=BRANCH,
        witness_token="signed.witness.token",
        witness_public_key_pem=b"independent-witness-public",
        attestation_signer_public_key_pem=b"test-signer-public",
        witness_issuer="northstar-controlled-witness",
        controller_id="isolated-jenkins-controller",
        job_full_name="Northstar/Trusted-Certification",
        environment="staging", source_commit="c" * 40,
        source_digest="a" * 64, target_digest="b" * 64, now=NOW,
    )
    return options, proven


async def persisted():
    options, proven = setup()
    index_receipt = await stage_witnessed_junit_custody(**options)
    row = options["session"].add.call_args.args[0]
    options["session"].get.return_value = row
    return options, proven, index_receipt, row


def reader_options(options):
    return {
        key: value for key, value in options.items() if key not in {
            "identity", "index_receipt", "receipts", "witness_token"
        }
    }


@pytest.mark.asyncio
async def test_verified_original_index_receipt_staged_without_auto_commit():
    options, proven, receipt, row = await persisted()
    assert receipt == options["index_receipt"]
    assert isinstance(row, NotificationJenkinsJunitCustodyRecord)
    assert row.release_id == RELEASE
    assert row.run_id == RUN
    assert row.witness_sha256 == proven.witness_sha256
    assert row.index_version_id == "locked-index-version-123"
    assert set(row.suite_receipts) == set(SUITES)
    assert row.suite_receipts["notification_worker"]["version_id"] == "notification_worker-version"
    options["identity"].verify.assert_awaited_once_with(run_id=RUN, branch=BRANCH)
    options["index_reconciler"].reconcile.assert_awaited_once()
    options["session"].flush.assert_awaited_once()
    options["session"].commit.assert_not_called()


@pytest.mark.asyncio
async def test_read_reconstructs_receipts_only_from_database():
    options, proven, original, row = await persisted()
    verified = await load_and_reconcile_witnessed_junit_custody(
        **reader_options(options)
    )
    assert verified == proven
    options["session"].get.assert_awaited_once_with(
        NotificationJenkinsJunitCustodyRecord, RELEASE
    )
    sent = options["index_reconciler"].reconcile.await_args.kwargs
    assert sent["index_receipt"] == original
    assert sent["receipts"]["notification_secrets"].version_id == "notification_secrets-version"
    assert sent["witness_token"] == row.witness_token


@pytest.mark.asyncio
async def test_wrong_aws_identity_denied_without_s3_or_db_access():
    options, _ = setup()
    options["identity"].verify.return_value = False
    with pytest.raises(PermissionError):
        await stage_witnessed_junit_custody(**options)
    options["index_reconciler"].reconcile.assert_not_awaited()
    options["session"].add.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_release_id_denied_without_s3_or_db_access():
    options, _ = setup()
    options["release_id"] = "../untrusted"
    with pytest.raises(JenkinsJunitCustodyRejected):
        await stage_witnessed_junit_custody(**options)
    options["index_reconciler"].reconcile.assert_not_awaited()
    options["session"].add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing-suite", "wrong-version", "wrong-key", "wrong-bucket", "bad-value"])
async def test_malformed_original_receipts_denied_before_s3(mutation):
    options, _ = setup()
    receipts = options["receipts"]
    if mutation == "missing-suite":
        receipts.pop("notification_worker")
    elif mutation == "wrong-version":
        receipts["notification_worker"] = replace(receipts["notification_worker"], version_id="")
    elif mutation == "wrong-key":
        receipts["notification_worker"] = replace(receipts["notification_worker"], key="unqualified.xml")
    elif mutation == "wrong-bucket":
        receipts["notification_worker"] = replace(receipts["notification_worker"], bucket="other-bucket")
    else:
        receipts["notification_worker"] = object()
    with pytest.raises(JenkinsJunitCustodyRejected):
        await stage_witnessed_junit_custody(**options)
    options["index_reconciler"].reconcile.assert_not_awaited()
    options["session"].add.assert_not_called()


@pytest.mark.asyncio
async def test_readback_failure_does_not_stage_unverified_receipt():
    options, _ = setup()
    options["index_reconciler"].reconcile.side_effect = RuntimeError("S3 Object Lock invalid")
    with pytest.raises(RuntimeError, match="Object Lock"):
        await stage_witnessed_junit_custody(**options)
    options["session"].add.assert_not_called()
    options["session"].flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_verifier_must_return_matching_build_coordinates():
    options, proven = setup()
    options["index_reconciler"].reconcile.return_value = replace(proven, source_commit="0" * 40)
    with pytest.raises(JenkinsJunitCustodyRejected):
        await stage_witnessed_junit_custody(**options)
    options["session"].add.assert_not_called()


@pytest.mark.asyncio
async def test_unique_conflict_bubbles_up_without_commit_or_overwrite():
    options, _ = setup()
    options["session"].flush.side_effect = RuntimeError("duplicate run")
    with pytest.raises(RuntimeError, match="duplicate run"):
        await stage_witnessed_junit_custody(**options)
    options["session"].commit.assert_not_called()
    options["session"].merge.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("altered", [
    {"run_id": "jenkins-other-run"},
    {"branch": "main"},
    {"environment": "production"},
    {"source_commit": "0" * 40},
    {"source_digest": "0" * 64},
    {"target_digest": "0" * 64},
])
async def test_read_does_not_accept_changed_protected_plan(altered):
    options, _, _, _row = await persisted()
    incoming = reader_options(options)
    incoming.update(altered)
    with pytest.raises(JenkinsJunitCustodyRejected):
        await load_and_reconcile_witnessed_junit_custody(**incoming)
    assert options["index_reconciler"].reconcile.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("altered", [
    {"index_version_id": ""},
    {"index_sha256": "not-a-checksum"},
    {"witness_sha256": "a" * 64},
])
async def test_invalid_database_receipts_or_witness_not_trusted(altered):
    options, _proven, _, row = await persisted()
    for key, value in altered.items():
        setattr(row, key, value)
    if "witness_sha256" in altered:
        # The mismatch is rejected only after independent S3 witness readback.
        with pytest.raises(JenkinsJunitCustodyRejected):
            await load_and_reconcile_witnessed_junit_custody(
                **reader_options(options)
            )
        assert options["index_reconciler"].reconcile.await_count == 2
    else:
        with pytest.raises(JenkinsJunitCustodyRejected):
            await load_and_reconcile_witnessed_junit_custody(**reader_options(options))


@pytest.mark.asyncio
async def test_missing_custody_row_is_not_a_qualified_release():
    options, _ = setup()
    options["session"].get.return_value = None
    with pytest.raises(JenkinsJunitCustodyRejected):
        await load_and_reconcile_witnessed_junit_custody(**reader_options(options))
    options["index_reconciler"].reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_suite_receipt_substitution_denied_before_s3():
    options, _proven, _receipt, row = await persisted()
    row.suite_receipts["notification_worker"]["version_id"] = ""
    with pytest.raises(JenkinsJunitCustodyRejected):
        await load_and_reconcile_witnessed_junit_custody(**reader_options(options))
    assert options["index_reconciler"].reconcile.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_clock", [0, False, "", [], {}, datetime(2026, 10, 10), datetime(2026, 10, 10, tzinfo=NoOffsetTZ())])
async def test_invalid_custody_clock_cannot_read_or_stage_evidence(bad_clock):
    options, _ = setup()
    options["now"] = bad_clock
    with pytest.raises(JenkinsJunitCustodyRejected, match="timezone-aware"):
        await load_and_reconcile_witnessed_junit_custody(**reader_options(options))
    options["session"].get.assert_not_awaited()
    with pytest.raises(JenkinsJunitCustodyRejected, match="timezone-aware"):
        await stage_witnessed_junit_custody(**options)
    options["index_reconciler"].reconcile.assert_not_awaited()
    options["session"].flush.assert_not_awaited()
