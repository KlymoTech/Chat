"""End-to-end fake-S3 tests for signed, versioned Jenkins JUnit evidence."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.aws_immutable_jenkins_junit_store import (
    AwsImmutableJenkinsJunitStore,
    JenkinsJunitArchiveConflict,
    JenkinsJunitArchiveUnknown,
)
from northstar_api.modules.platform_runtime.aws_jenkins_junit_reconciliation import (
    JenkinsJunitIntegrityError,
    JenkinsJunitReadUnknown,
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


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _public(private: Ed25519PrivateKey) -> bytes:
    return private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def fixture():
    witness_key, attestation_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    reports = {
        suite: (
            f'<testsuite name="{suite}" tests="1" failures="0" errors="0" skipped="0">'
            '<testcase name="passed"/></testsuite>'
        ).encode() for suite in SUITES
    }
    statement = {
        "version": 1,
        "witness_issuer": "northstar-controlled-witness",
        "controller_id": "isolated-jenkins-controller",
        "job_full_name": "Northstar/Trusted-Certification",
        "run_id": RUN,
        "branch": BRANCH,
        "environment": "staging",
        "source_commit": "c" * 40,
        "source_digest": "a" * 64,
        "target_digest": "b" * 64,
        "started_at": int((NOW - timedelta(seconds=110)).timestamp()),
        "finished_at": int((NOW - timedelta(seconds=5)).timestamp()),
        "suites": {
            suite: {"sha256": hashlib.sha256(data).hexdigest(), "tests_run": 1}
            for suite, data in reports.items()
        },
    }
    raw = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    witness = _b64(raw) + "." + _b64(witness_key.sign(raw))
    kwargs = {
        "release_id": RELEASE,
        "witness_token": witness,
        "witness_public_key_pem": _public(witness_key),
        "attestation_signer_public_key_pem": _public(attestation_key),
        "witness_issuer": statement["witness_issuer"],
        "controller_id": statement["controller_id"],
        "job_full_name": statement["job_full_name"],
        "run_id": RUN, "branch": BRANCH, "environment": "staging",
        "source_commit": "c" * 40, "source_digest": "a" * 64,
        "target_digest": "b" * 64, "junit_reports": reports, "now": NOW,
    }
    return kwargs


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.heads = []
        self.gets = []
        self.break_on_write = None

    def put_object(self, **kw):
        if self.break_on_write is not None and len(self.writes) == self.break_on_write:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        key = kw["Key"]
        if key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        version = f"immutable-version-{len(self.objects) + 1}"
        self.writes.append(kw)
        self.objects[key] = {"arguments": kw, "version": version}
        return {"VersionId": version, "ChecksumSHA256": kw["ChecksumSHA256"]}

    def _read(self, kw):
        key = kw["Key"]
        if key not in self.objects or self.objects[key]["version"] != kw["VersionId"]:
            raise ClientError({"Error": {"Code": "NoSuchVersion"}}, "GetObject")
        return self.objects[key]

    def head_object(self, **kw):
        self.heads.append(kw)
        result = self._read(kw)
        req = result["arguments"]
        return {
            "VersionId": result["version"],
            "ContentLength": len(req["Body"]),
            "ContentType": req["ContentType"],
            "ServerSideEncryption": req["ServerSideEncryption"],
            "SSEKMSKeyId": req["SSEKMSKeyId"],
            "ObjectLockMode": req["ObjectLockMode"],
            "ObjectLockRetainUntilDate": req["ObjectLockRetainUntilDate"],
            "Metadata": req["Metadata"].copy(),
        }

    def get_object(self, **kw):
        self.gets.append(kw)
        result = self._read(kw)
        return {"VersionId": result["version"], "Body": io.BytesIO(result["arguments"]["Body"])}


def pair():
    args = fixture()
    s3 = FakeS3()
    writer = AwsImmutableJenkinsJunitStore(
        bucket=BUCKET, region="us-east-1", account_id="123456789012",
        kms_key_arn=KMS, s3_client=s3,
    )
    reader = ReadOnlyWitnessedJunitReconciler(
        bucket=BUCKET, kms_key_arn=KMS, s3_client=s3,
    )
    return args, s3, writer, reader


async def archived():
    args, s3, writer, reader = pair()
    result = await writer.archive_witnessed_reports(
        authorized_publisher=True, **args
    )
    return args, s3, reader, result


@pytest.mark.asyncio
async def test_end_to_end_write_and_read_three_exact_versioned_objects():
    args, s3, reader, result = await archived()
    assert len(result.receipts) == 3
    assert len(s3.writes) == 3
    for suite, receipt in result.receipts:
        assert receipt.key == f"evidence/{RELEASE}/jenkins/{RUN}/junit/{suite}.xml"
        assert receipt.version_id.startswith("immutable-version-")
        req = s3.objects[receipt.key]["arguments"]
        assert req["IfNoneMatch"] == "*"
        assert req["ObjectLockMode"] == "COMPLIANCE"
        assert req["ObjectLockRetainUntilDate"] > NOW + timedelta(days=90)
        assert req["ServerSideEncryption"] == "aws:kms"
        assert req["SSEKMSKeyId"] == KMS
        assert base64.b64decode(req["ChecksumSHA256"]) == hashlib.sha256(req["Body"]).digest()
        assert req["Metadata"]["witness-sha256"] == result.provenance.witness_sha256
    args.pop("junit_reports")
    verified = await reader.reconcile(receipts=dict(result.receipts), **args)
    assert verified == result.provenance
    assert len(s3.heads) == len(s3.gets) == 3
    assert all("VersionId" in request for request in s3.gets)


@pytest.mark.asyncio
async def test_unauthorized_publisher_never_writes():
    args, s3, writer, _ = pair()
    with pytest.raises(PermissionError):
        await writer.archive_witnessed_reports(authorized_publisher=False, **args)
    assert not s3.writes


@pytest.mark.asyncio
async def test_wrong_approved_build_or_tampered_witness_never_writes():
    args, s3, writer, _ = pair()
    args["source_commit"] = "f" * 40
    with pytest.raises(JenkinsProvenanceRejected):
        await writer.archive_witnessed_reports(authorized_publisher=True, **args)
    assert not s3.writes


@pytest.mark.asyncio
async def test_failed_junit_never_writes_any_report():
    args, s3, writer, _ = pair()
    args["junit_reports"]["notification_egress"] = (
        b'<testsuite name="notification_egress" tests="1" failures="1" errors="0" skipped="0">'
        b'<testcase name="x"><failure/></testcase></testsuite>'
    )
    with pytest.raises(JenkinsProvenanceRejected):
        await writer.archive_witnessed_reports(authorized_publisher=True, **args)
    assert not s3.writes


@pytest.mark.asyncio
async def test_report_conflict_is_blocking_without_retries():
    args, s3, writer, _ = pair()
    s3.break_on_write = 1
    with pytest.raises(JenkinsJunitArchiveConflict):
        await writer.archive_witnessed_reports(authorized_publisher=True, **args)
    assert len(s3.writes) == 1


@pytest.mark.asyncio
async def test_unconfirmed_version_is_blocking():
    args, s3, writer, _ = pair()
    s3.put_object = MagicMock(return_value={})
    with pytest.raises(JenkinsJunitArchiveUnknown):
        await writer.archive_witnessed_reports(authorized_publisher=True, **args)
    assert s3.put_object.call_count == 1


@pytest.mark.asyncio
async def test_wrong_receipt_version_refused_before_s3_lookup():
    args, s3, reader, stored = await archived()
    receipts = dict(stored.receipts)
    receipts["notification_worker"] = replace(
        receipts["notification_worker"], key="outside/evidence.xml"
    )
    args.pop("junit_reports")
    with pytest.raises(JenkinsJunitIntegrityError):
        await reader.reconcile(receipts=receipts, **args)
    assert not s3.heads and not s3.gets


@pytest.mark.asyncio
async def test_wrong_pinned_s3_version_is_never_replaced_by_latest():
    args, s3, reader, stored = await archived()
    receipts = dict(stored.receipts)
    receipts["notification_worker"] = replace(
        receipts["notification_worker"], version_id="other-version"
    )
    args.pop("junit_reports")
    with pytest.raises(JenkinsJunitVersionMissing):
        await reader.reconcile(receipts=receipts, **args)
    assert not s3.writes[3:]


@pytest.mark.asyncio
@pytest.mark.parametrize("attribute,value", [
    ("SSEKMSKeyId", "wrong-kms"),
    ("ObjectLockMode", "GOVERNANCE"),
    ("ObjectLockRetainUntilDate", NOW - timedelta(days=1)),
    ("ContentType", "text/plain"),
    ("source-commit", "f" * 40),
    ("witness-sha256", "f" * 64),
])
async def test_tampered_object_headers_fail_closed(attribute, value):
    args, s3, reader, stored = await archived()
    key = dict(stored.receipts)["notification_egress"].key
    obj = s3.objects[key]["arguments"]
    if attribute in obj["Metadata"]:
        obj["Metadata"][attribute] = value
    else:
        obj[attribute] = value
    args.pop("junit_reports")
    with pytest.raises(JenkinsJunitIntegrityError):
        await reader.reconcile(receipts=dict(stored.receipts), **args)


@pytest.mark.asyncio
async def test_modified_s3_content_is_not_signed_evidence():
    args, s3, reader, stored = await archived()
    key = dict(stored.receipts)["notification_egress"].key
    original = s3.objects[key]["arguments"]["Body"]
    s3.objects[key]["arguments"]["Body"] = original.replace(b"passed", b"failed")
    args.pop("junit_reports")
    with pytest.raises(JenkinsJunitIntegrityError):
        await reader.reconcile(receipts=dict(stored.receipts), **args)


@pytest.mark.asyncio
async def test_valid_objects_wrong_witness_signature_fail_after_readback():
    args, s3, reader, stored = await archived()
    args.pop("junit_reports")
    args["witness_token"] += "altered"
    with pytest.raises(JenkinsProvenanceRejected):
        await reader.reconcile(receipts=dict(stored.receipts), **args)
    assert len(s3.gets) == 3


@pytest.mark.asyncio
async def test_s3_unknown_read_does_not_mutate_objects():
    args, s3, reader, stored = await archived()
    prior_writes = len(s3.writes)
    args.pop("junit_reports")
    s3.head_object = MagicMock(side_effect=RuntimeError("AWS unavailable"))
    with pytest.raises(JenkinsJunitReadUnknown):
        await reader.reconcile(receipts=dict(stored.receipts), **args)
    assert len(s3.writes) == prior_writes


@pytest.mark.asyncio
async def test_s3_missing_object_version_reported_distinctly():
    args, s3, reader, stored = await archived()
    args.pop("junit_reports")
    del s3.objects[dict(stored.receipts)["notification_egress"].key]
    with pytest.raises(JenkinsJunitVersionMissing):
        await reader.reconcile(receipts=dict(stored.receipts), **args)


def test_invalid_store_and_reader_configuration_rejected():
    _, s3, _, _ = pair()
    base = dict(
        bucket=BUCKET, region="us-east-1", account_id="123456789012",
        kms_key_arn=KMS, s3_client=s3,
    )
    for invalid in (
        {"bucket": "../unsafe"}, {"region": "invalid"},
        {"account_id": "000"}, {"kms_key_arn": KMS.replace("123456789012", "999999999999")},
        {"retention_days": 30}, {"timeout_seconds": 0},
    ):
        with pytest.raises(ValueError):
            AwsImmutableJenkinsJunitStore(**(base | invalid))
    with pytest.raises(ValueError):
        ReadOnlyWitnessedJunitReconciler(
            bucket=BUCKET, kms_key_arn="incorrect", s3_client=s3,
        )
