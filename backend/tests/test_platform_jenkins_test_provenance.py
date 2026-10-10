"""Independent Jenkins witness must match real JUnit bytes and pinned build."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta, tzinfo

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.queue_notification_jenkins_test_provenance import (
    JenkinsProvenanceRejected,
    verify_witnessed_jenkins_reports,
)

class NoOffsetTZ(tzinfo):
    def utcoffset(self, dt):
        return None


NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
SOURCES = {"notification_worker", "notification_egress", "notification_secrets"}


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def pem(private: Ed25519PrivateKey) -> bytes:
    return private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def make_junit(name: str, *, status: str = "passed") -> bytes:
    child = f'<testcase name="completed"><{status}/></testcase>' if status != "passed" else '<testcase name="completed"/>'
    attrs = 'tests="1" failures="0" errors="0" skipped="0"'
    return f'<testsuite name="{name}" {attrs}>{child}</testsuite>'.encode()


def harness():
    witness_private = Ed25519PrivateKey.generate()
    signer_private = Ed25519PrivateKey.generate()
    reports = {name: make_junit(name) for name in SOURCES}
    record = {
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
        "started_at": int((NOW - timedelta(minutes=3)).timestamp()),
        "finished_at": int((NOW - timedelta(seconds=3)).timestamp()),
        "suites": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "tests_run": 1}
            for name, data in reports.items()
        },
    }
    params = {
        "witness_public_key_pem": pem(witness_private),
        "attestation_signer_public_key_pem": pem(signer_private),
        "witness_issuer": record["witness_issuer"],
        "controller_id": record["controller_id"],
        "job_full_name": record["job_full_name"],
        "run_id": RUN,
        "branch": BRANCH,
        "environment": "staging",
        "source_commit": "c" * 40,
        "source_digest": "a" * 64,
        "target_digest": "b" * 64,
        "junit_reports": reports,
        "now": NOW,
    }
    return witness_private, record, params


def signed(private: Ed25519PrivateKey, record: dict) -> str:
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return b64(raw) + "." + b64(private.sign(raw))


def verify(private, record, params):
    return verify_witnessed_jenkins_reports(signed(private, record), **params)


def test_pinned_witness_and_all_three_real_junit_suites():
    private, record, params = harness()
    result = verify(private, record, params)
    assert result.run_id == RUN
    assert result.source_commit == "c" * 40
    assert dict(result.tests_run) == {k: 1 for k in SOURCES}
    assert len(result.witness_sha256) == 64
    assert result.finished_at == record["finished_at"]


@pytest.mark.parametrize("change", [
    {"witness_issuer": "untrusted-controller"},
    {"controller_id": "another-controller"},
    {"job_full_name": "Another/Job"},
    {"run_id": "jenkins-other-build"},
    {"branch": "main"},
    {"environment": "production"},
    {"source_commit": "d" * 40},
    {"source_digest": "d" * 64},
    {"target_digest": "d" * 64},
    {"finished_at": int((NOW + timedelta(minutes=1)).timestamp())},
    {"finished_at": int((NOW - timedelta(minutes=16)).timestamp())},
    {"started_at": int((NOW - timedelta(hours=3)).timestamp())},
])
def test_wrong_or_expired_signed_job_provenance_is_rejected(change):
    private, record, params = harness()
    record.update(change)
    with pytest.raises(JenkinsProvenanceRejected):
        verify(private, record, params)


@pytest.mark.parametrize("field", [
    "controller_id", "job_full_name", "branch", "source_digest", "source_commit",
])
def test_expected_metadata_must_come_from_protected_plan(field):
    private, record, params = harness()
    params[field] = "not-original"
    with pytest.raises(JenkinsProvenanceRejected):
        verify(private, record, params)


def test_signature_tampering_is_detected():
    private, record, params = harness()
    other = {**record, "environment": "production"}
    original = signed(private, record)
    forged = signed(private, other).split(".")[0] + "." + original.split(".")[1]
    with pytest.raises(JenkinsProvenanceRejected):
        verify_witnessed_jenkins_reports(forged, **params)


def test_key_rotation_without_independent_pin_is_rejected():
    private, record, params = harness()
    params["witness_public_key_pem"] = pem(Ed25519PrivateKey.generate())
    with pytest.raises(JenkinsProvenanceRejected):
        verify(private, record, params)


def test_self_witnessing_with_attestation_signer_key_rejected():
    private, record, params = harness()
    params["attestation_signer_public_key_pem"] = pem(private)
    with pytest.raises(JenkinsProvenanceRejected):
        verify(private, record, params)


@pytest.mark.parametrize("suite_change", ["missing", "extra", "wrong-hash", "zero-tests"])
def test_missing_or_inconsistent_witnessed_suite_set_rejected(suite_change):
    private, record, params = harness()
    if suite_change == "missing":
        record["suites"].pop("notification_worker")
    if suite_change == "extra":
        record["suites"]["unplanned_suite"] = {"sha256": "f" * 64, "tests_run": 1}
    if suite_change == "wrong-hash":
        record["suites"]["notification_worker"]["sha256"] = "f" * 64
    if suite_change == "zero-tests":
        record["suites"]["notification_worker"]["tests_run"] = 0
    with pytest.raises(JenkinsProvenanceRejected):
        verify(private, record, params)


@pytest.mark.parametrize("report", [
    b'<testsuite name="notification_worker" tests="1" failures="1" errors="0" skipped="0"><testcase name="x"><failure/></testcase></testsuite>',
    b'<testsuite name="notification_worker" tests="1" failures="0" errors="0" skipped="1"><testcase name="x"><skipped/></testcase></testsuite>',
    b'<testsuite name="notification_worker" tests="1" failures="0" errors="0" skipped="0"><testcase name="x"><error/></testcase></testsuite>',
    b'<testsuite name="notification_worker" tests="2" failures="0" errors="0" skipped="0"><testcase name="x"/></testsuite>',
    b'<testsuite name="wrong-suite" tests="1" failures="0" errors="0" skipped="0"><testcase name="x"/></testsuite>',
    b'<testsuite name="notification_worker" tests="0" failures="0" errors="0" skipped="0"></testsuite>',
    b'<!DOCTYPE test [<!ENTITY steal SYSTEM "file:///etc/passwd">]><testsuite name="notification_worker"/>',
    b'<testsuite name="notification_worker" tests="1" failures="0" errors="0" skipped="0"><testcase name="x"><skipped/></testcase></testsuite>',
    b'not xml',
])
def test_failed_skipped_empty_or_hostile_junit_rejected_even_if_witness_signs_it(report):
    private, record, params = harness()
    params["junit_reports"]["notification_worker"] = report
    record["suites"]["notification_worker"]["sha256"] = hashlib.sha256(report).hexdigest()
    with pytest.raises(JenkinsProvenanceRejected):
        verify(private, record, params)


def test_report_bytes_must_match_witness_hash():
    private, record, params = harness()
    params["junit_reports"]["notification_worker"] = params["junit_reports"]["notification_worker"].replace(b"completed", b"other")
    with pytest.raises(JenkinsProvenanceRejected):
        verify(private, record, params)


def test_report_set_must_be_exact_even_with_valid_witness():
    private, record, params = harness()
    params["junit_reports"]["other"] = b"some bytes"
    with pytest.raises(JenkinsProvenanceRejected):
        verify(private, record, params)


def test_duplicate_signed_witness_keys_rejected():
    private, record, params = harness()
    raw = json.dumps(record, separators=(",", ":")).encode()
    raw = raw[:-1] + b',"branch":"main"}'
    token = b64(raw) + "." + b64(private.sign(raw))
    with pytest.raises(JenkinsProvenanceRejected):
        verify_witnessed_jenkins_reports(token, **params)


@pytest.mark.parametrize("bad", [
    "no-signature",
    "abc.invalid*characters",
    "a" * 16400,
    "",
])
def test_malformed_witness_token_rejected(bad):
    _, _, params = harness()
    with pytest.raises(JenkinsProvenanceRejected):
        verify_witnessed_jenkins_reports(bad, **params)


def test_naive_verification_timestamp_rejected():
    private, record, params = harness()
    params["now"] = datetime(2026, 10, 10)
    with pytest.raises(JenkinsProvenanceRejected):
        verify(private, record, params)


@pytest.mark.parametrize("bad_clock", [0, False, "", [], {}, datetime(2026, 10, 10, tzinfo=NoOffsetTZ())])
def test_invalid_raw_junit_verification_clock_rejected_before_witness_validation(bad_clock):
    private, record, params = harness()
    params["now"] = bad_clock
    with pytest.raises(JenkinsProvenanceRejected, match="timezone-aware"):
        verify(private, record, params)
