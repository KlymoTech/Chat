"""Immutable index owns the original S3 versions and signed Jenkins witness."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.aws_immutable_jenkins_junit_store import (
    AwsImmutableJenkinsJunitStore,
)
from northstar_api.modules.platform_runtime.aws_jenkins_junit_evidence_index import (
    AwsJenkinsJunitEvidenceIndex,
    JunitIndexConflict,
    JunitIndexIntegrityError,
    JunitIndexReadUnknown,
    JunitIndexVersionMissing,
    JunitIndexWriteUnknown,
)
from northstar_api.modules.platform_runtime.aws_jenkins_junit_reconciliation import (
    JenkinsJunitVersionMissing,
    ReadOnlyWitnessedJunitReconciler,
)
from northstar_api.modules.platform_runtime.queue_notification_jenkins_test_provenance import (
    JenkinsProvenanceRejected,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
BUCKET = "northstar-qualification-artifacts"
KMS = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
RELEASE = "release-123456"
RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
SUITES = ("notification_egress", "notification_secrets", "notification_worker")


def _public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.gets = []
        self.heads = []
        self.fail_put = None
        self.fail_get = None

    def put_object(self, **kwargs):
        if self.fail_put is not None:
            raise self.fail_put
        key = kwargs["Key"]
        if key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        version = f"locked-version-{len(self.objects) + 1}"
        self.objects[key] = (version, kwargs)
        self.writes.append(kwargs)
        return {"VersionId": version, "ChecksumSHA256": kwargs["ChecksumSHA256"]}

    def head_object(self, **kwargs):
        self.heads.append(kwargs)
        version, args = self._lookup(kwargs)
        return dict(
            VersionId=version,
            ContentLength=len(args["Body"]),
            ContentType=args["ContentType"],
            ServerSideEncryption=args["ServerSideEncryption"],
            SSEKMSKeyId=args["SSEKMSKeyId"],
            ObjectLockMode=args["ObjectLockMode"],
            ObjectLockRetainUntilDate=args["ObjectLockRetainUntilDate"],
            Metadata=args["Metadata"].copy(),
        )

    def get_object(self, **kwargs):
        self.gets.append(kwargs)
        if self.fail_get is not None and kwargs["Key"].endswith("/verified-index.json"):
            raise self.fail_get
        version, args = self._lookup(kwargs)
        return {"VersionId": version, "Body": io.BytesIO(args["Body"])}

    def _lookup(self, kwargs):
        item = self.objects.get(kwargs["Key"])
        if item is None or item[0] != kwargs["VersionId"]:
            raise ClientError({"Error": {"Code": "NoSuchVersion"}}, "GetObject")
        return item


def fixture():
    witness_signer = Ed25519PrivateKey.generate()
    attestation_signer = Ed25519PrivateKey.generate()
    reports = {
        name: (
            f'<testsuite name="{name}" tests="1" failures="0" errors="0" skipped="0">'
            '<testcase name="checked"/></testsuite>'
        ).encode()
        for name in SUITES
    }
    witness = {
        "version": 1, "witness_issuer": "northstar-controlled-witness",
        "controller_id": "isolated-jenkins-controller",
        "job_full_name": "Northstar/Trusted-Certification",
        "run_id": RUN, "branch": BRANCH, "environment": "staging",
        "source_commit": "c" * 40,
        "source_digest": "a" * 64, "target_digest": "b" * 64,
        "started_at": int((NOW - timedelta(minutes=3)).timestamp()),
        "finished_at": int((NOW - timedelta(seconds=5)).timestamp()),
        "suites": {
            name: {"sha256": hashlib.sha256(raw).hexdigest(), "tests_run": 1}
            for name, raw in reports.items()
        },
    }
    raw = json.dumps(witness, sort_keys=True, separators=(",", ":")).encode()
    witness_token = _encode(raw) + "." + _encode(witness_signer.sign(raw))
    plan = dict(
        release_id=RELEASE, witness_token=witness_token,
        witness_public_key_pem=_public(witness_signer),
        attestation_signer_public_key_pem=_public(attestation_signer),
        witness_issuer=witness["witness_issuer"],
        controller_id=witness["controller_id"],
        job_full_name=witness["job_full_name"],
        run_id=RUN, branch=BRANCH, environment="staging",
        source_commit="c" * 40,
        source_digest="a" * 64, target_digest="b" * 64,
        now=NOW,
    )
    s3 = FakeS3()
    config = dict(bucket=BUCKET, kms_key_arn=KMS, s3_client=s3)
    reports_writer = AwsImmutableJenkinsJunitStore(
        **config, region="us-east-1", account_id="123456789012",
    )
    report_reader = ReadOnlyWitnessedJunitReconciler(**config)
    index = AwsJenkinsJunitEvidenceIndex(
        **config, region="us-east-1", account_id="123456789012",
    )
    identity = SimpleNamespace(verify=AsyncMock(return_value=True))
    return plan, reports, s3, reports_writer, report_reader, index, identity


async def populated():
    plan, reports, s3, writer, report_reader, index, identity = fixture()
    saved = await writer.archive_witnessed_reports(
        identity=identity, junit_reports=reports, **plan
    )
    return plan, s3, report_reader, index, identity, dict(saved.receipts)


async def indexed():
    plan, s3, report_reader, index, identity, receipts = await populated()
    result = await index.publish(
        identity=identity, report_reconciler=report_reader,
        receipts=receipts, **plan,
    )
    return plan, s3, report_reader, index, identity, receipts, result


@pytest.mark.asyncio
async def test_three_real_locked_reports_before_single_signed_index_and_exact_readback():
    plan, s3, reader, index, identity, receipts, result = await indexed()
    assert len(s3.writes) == 4
    assert result.receipt.key == f"evidence/{RELEASE}/jenkins/{RUN}/junit/verified-index.json"
    request = s3.writes[-1]
    assert request["IfNoneMatch"] == "*"
    assert request["ServerSideEncryption"] == "aws:kms"
    assert request["SSEKMSKeyId"] == KMS
    assert request["ObjectLockMode"] == "COMPLIANCE"
    assert request["ObjectLockRetainUntilDate"] >= NOW + timedelta(days=91)
    assert base64.b64decode(request["ChecksumSHA256"]) == hashlib.sha256(request["Body"]).digest()
    payload = json.loads(request["Body"])
    assert payload["witness_token"] == plan["witness_token"]
    assert set(payload["suites"]) == set(SUITES)
    assert payload["suites"]["notification_worker"]["version_id"] == receipts["notification_worker"].version_id
    verified = await index.reconcile(
        index_receipt=result.receipt, report_reconciler=reader,
        receipts=receipts, **plan,
    )
    assert verified == result.provenance
    assert len(s3.heads) == len(s3.gets) == 7
    assert all("VersionId" in request for request in s3.gets)
    identity.verify.assert_awaited()


@pytest.mark.asyncio
async def test_writer_denies_untrusted_role_before_any_index_write():
    plan, s3, reader, index, identity, receipts = await populated()
    identity.verify.return_value = False
    with pytest.raises(PermissionError):
        await index.publish(identity=identity, report_reconciler=reader, receipts=receipts, **plan)
    assert len(s3.writes) == 3


@pytest.mark.asyncio
async def test_witness_signature_mismatch_blocks_index_creation():
    plan, s3, reader, index, identity, receipts = await populated()
    plan["witness_token"] += "tamper"
    with pytest.raises(JenkinsProvenanceRejected):
        await index.publish(identity=identity, report_reconciler=reader, receipts=receipts, **plan)
    assert len(s3.writes) == 3


@pytest.mark.asyncio
async def test_wrong_original_report_version_blocks_index_creation():
    plan, s3, reader, index, identity, receipts = await populated()
    receipts["notification_worker"] = replace(receipts["notification_worker"], version_id="foreign")
    with pytest.raises(JenkinsJunitVersionMissing):
        await index.publish(identity=identity, report_reconciler=reader, receipts=receipts, **plan)
    assert len(s3.writes) == 3


@pytest.mark.asyncio
async def test_duplicate_index_is_never_overwritten_or_retried():
    plan, s3, reader, index, identity, receipts, result = await indexed()
    with pytest.raises(JunitIndexConflict):
        await index.publish(identity=identity, report_reconciler=reader, receipts=receipts, **plan)
    assert len(s3.writes) == 4
    assert result.receipt.key in s3.objects


@pytest.mark.asyncio
async def test_unknown_write_failure_is_blocking_without_retry():
    plan, s3, reader, index, identity, receipts = await populated()
    s3.fail_put = ConnectionError("network failure")
    with pytest.raises(JunitIndexWriteUnknown):
        await index.publish(identity=identity, report_reconciler=reader, receipts=receipts, **plan)
    assert len(s3.writes) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    "version", "checksum", "key", "bucket",
])
async def test_unpinned_index_receipt_denied_before_read(mutation):
    plan, s3, reader, index, identity, receipts, result = await indexed()
    before = len(s3.gets)
    original = result.receipt
    changes = {
        "version": {"version_id": ""},
        "checksum": {"sha256": "f" * 64},
        "key": {"key": "not/a/qualified/index.json"},
        "bucket": {"bucket": "foreign-evidence"},
    }
    with pytest.raises(JunitIndexIntegrityError):
        await index.reconcile(
            index_receipt=replace(original, **changes[mutation]),
            report_reconciler=reader, receipts=receipts, **plan,
        )
    if mutation != "checksum":
        # Some invalid receipts are rejected without any report readback.
        assert len(s3.gets) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("attribute,value", [
    ("ObjectLockMode", "GOVERNANCE"),
    ("SSEKMSKeyId", "wrong-key"),
    ("ContentType", "text/plain"),
    ("ObjectLockRetainUntilDate", NOW - timedelta(days=1)),
    ("witness-sha256", "f" * 64),
    ("source-commit", "e" * 40),
])
async def test_index_object_lock_metadata_and_provenance_fail_closed(attribute, value):
    plan, s3, reader, index, identity, receipts, result = await indexed()
    args = s3.objects[result.receipt.key][1]
    if attribute in args["Metadata"]:
        args["Metadata"][attribute] = value
    else:
        args[attribute] = value
    with pytest.raises(JunitIndexIntegrityError):
        await index.reconcile(
            index_receipt=result.receipt, report_reconciler=reader,
            receipts=receipts, **plan,
        )


@pytest.mark.asyncio
async def test_altered_index_contents_fail_even_if_some_metadata_looks_right():
    plan, s3, reader, index, identity, receipts, result = await indexed()
    args = s3.objects[result.receipt.key][1]
    args["Body"] = args["Body"].replace(b"staging", b"testing")
    with pytest.raises(JunitIndexIntegrityError):
        await index.reconcile(
            index_receipt=result.receipt, report_reconciler=reader,
            receipts=receipts, **plan,
        )


@pytest.mark.asyncio
async def test_no_latest_key_fallback_when_index_original_version_is_missing():
    plan, s3, reader, index, identity, receipts, result = await indexed()
    s3.objects.pop(result.receipt.key)
    with pytest.raises(JunitIndexVersionMissing):
        await index.reconcile(
            index_receipt=result.receipt, report_reconciler=reader,
            receipts=receipts, **plan,
        )


@pytest.mark.asyncio
async def test_unknown_index_get_blocks_and_performs_no_writes():
    plan, s3, reader, index, identity, receipts, result = await indexed()
    s3.fail_get = ConnectionError("S3 unknown")
    count = len(s3.writes)
    with pytest.raises(JunitIndexReadUnknown):
        await index.reconcile(
            index_receipt=result.receipt, report_reconciler=reader,
            receipts=receipts, **plan,
        )
    assert len(s3.writes) == count


def test_store_constructor_rejects_wrong_bucket_iam_and_retention():
    _, _, s3, _, _, _, _ = fixture()
    base = dict(
        bucket=BUCKET, kms_key_arn=KMS, s3_client=s3,
        region="us-east-1", account_id="123456789012",
    )
    for bad in (
        {"bucket": "../bad"},
        {"account_id": "123"},
        {"kms_key_arn": KMS.replace("123456789012", "111111111111")},
        {"retention_days": 1},
        {"timeout_seconds": 0},
    ):
        with pytest.raises(ValueError):
            AwsJenkinsJunitEvidenceIndex(**(base | bad))
