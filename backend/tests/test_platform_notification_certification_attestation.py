"""Independently signed test results must gate secret access and qualification."""
import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.qualification import verify_qualification_proofs
from northstar_api.modules.platform_runtime.queue_notification_certification_attestation import (
    CertificationAttestationError,
    issue_verified_notification_qualification_proofs,
    verify_jenkins_certification_result,
)
from northstar_api.modules.platform_runtime.queue_notification_worker_qualification import (
    PersistedNotificationWorkerQualification,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
COMMIT = "c" * 40
SOURCE = "a" * 64
TARGET = "b" * 64
SIGNING_KEY = b"k" * 32
REQUIRED = frozenset(PersistedNotificationWorkerQualification.REQUIRED)


def public_pem(private):
    return private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def report(**changes):
    document = {
        "version": 1,
        "issuer": "northstar-isolated-test-runner",
        "run_id": RUN,
        "branch": BRANCH,
        "environment": "staging",
        "source_commit": COMMIT,
        "source_digest": SOURCE,
        "target_digest": TARGET,
        "started_at": int((NOW - timedelta(minutes=5)).timestamp()),
        "finished_at": int((NOW - timedelta(seconds=10)).timestamp()),
        "suites": {
            name: {"status": "passed", "tests_run": 4, "tests_failed": 0, "tests_skipped": 0}
            for name in REQUIRED
        },
    }
    document.update(changes)
    return document


def signed(document, private):
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return b64(raw) + "." + b64(private.sign(raw))


def args(private, **changes):
    result = dict(
        test_runner_public_key_pem=public_pem(private),
        issuer="northstar-isolated-test-runner",
        run_id=RUN, branch=BRANCH, environment="staging",
        source_commit=COMMIT, source_digest=SOURCE,
        target_digest=TARGET, now=NOW,
    )
    result.update(changes)
    return result


def test_all_signed_passing_suites_verify():
    private = Ed25519PrivateKey.generate()
    assert verify_jenkins_certification_result(
        signed(report(), private), **args(private)
    ) == REQUIRED


@pytest.mark.parametrize("suite_change", [
    {"status": "failed"},
    {"status": "skipped"},
    {"status": "passed", "tests_run": 0},
    {"status": "passed", "tests_skipped": 1},
    {"status": "passed", "tests_failed": 1},
])
def test_failed_incomplete_or_skipped_results_are_denied(suite_change):
    private = Ed25519PrivateKey.generate()
    suites = report()["suites"]
    suites["notification_worker"].update(suite_change)
    with pytest.raises(CertificationAttestationError):
        verify_jenkins_certification_result(
            signed(report(suites=suites), private), **args(private)
        )


@pytest.mark.parametrize("missing", list(REQUIRED))
def test_missing_required_suite_is_denied(missing):
    private = Ed25519PrivateKey.generate()
    suites = report()["suites"]
    suites.pop(missing)
    with pytest.raises(CertificationAttestationError):
        verify_jenkins_certification_result(
            signed(report(suites=suites), private), **args(private)
        )


@pytest.mark.parametrize("changed", [
    {"issuer": "untrusted-test-runner"},
    {"run_id": "jenkins-build-999"},
    {"branch": "main"},
    {"environment": "production"},
    {"source_commit": "d" * 40},
    {"source_digest": "c" * 64},
    {"target_digest": "d" * 64},
    {"finished_at": int((NOW - timedelta(minutes=16)).timestamp())},
    {"finished_at": int((NOW + timedelta(minutes=1)).timestamp())},
])
def test_mismatched_or_expired_signed_result_is_denied(changed):
    private = Ed25519PrivateKey.generate()
    with pytest.raises(CertificationAttestationError):
        verify_jenkins_certification_result(
            signed(report(**changed), private), **args(private)
        )


def test_untrusted_signer_and_tampering_are_denied():
    private = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    attestation = signed(report(), private)
    with pytest.raises(CertificationAttestationError):
        verify_jenkins_certification_result(attestation, **args(other))
    changed = signed(report(), private)
    encoded, signature = changed.split(".")
    forged = signed(report(branch="main"), private).split(".")[0] + "." + signature
    assert encoded != forged.split(".")[0]
    with pytest.raises(CertificationAttestationError):
        verify_jenkins_certification_result(forged, **args(private))


@pytest.mark.asyncio
async def test_valid_attestation_issues_existing_runtime_verifiable_proofs():
    private = Ed25519PrivateKey.generate()
    store = SimpleNamespace(retrieve=AsyncMock(return_value=SIGNING_KEY))
    tokens = await issue_verified_notification_qualification_proofs(
        attestation_token=signed(report(), private),
        signing_key_store=store,
        **args(private),
    )
    assert len(tokens) == len(REQUIRED)
    store.retrieve.assert_awaited_once_with(run_id=RUN)
    assert not verify_qualification_proofs(
        tokens, required=tuple(sorted(REQUIRED)), environment="staging",
        source_digest=SOURCE, target_digest=TARGET, signing_key=SIGNING_KEY,
        now=NOW,
    )


@pytest.mark.asyncio
async def test_invalid_attestation_cannot_access_signing_key():
    private = Ed25519PrivateKey.generate()
    store = SimpleNamespace(retrieve=AsyncMock(return_value=SIGNING_KEY))
    with pytest.raises(CertificationAttestationError):
        await issue_verified_notification_qualification_proofs(
            attestation_token=signed(report(branch="main"), private),
            signing_key_store=store,
            **args(private),
        )
    store.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_iam_qualified_key_fails_without_issuing():
    private = Ed25519PrivateKey.generate()
    store = SimpleNamespace(retrieve=AsyncMock(return_value=None))
    with pytest.raises(PermissionError):
        await issue_verified_notification_qualification_proofs(
            attestation_token=signed(report(), private),
            signing_key_store=store,
            **args(private),
        )
