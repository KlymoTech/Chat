"""Fail-closed unit tests for the internal custody-first attestation signer."""
from __future__ import annotations

import json
from datetime import UTC, datetime, tzinfo

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime import queue_notification_custody_attestation_signer as subject
from northstar_api.modules.platform_runtime.queue_notification_jenkins_test_provenance import VerifiedJenkinsProvenance


class NoOffsetTZ(tzinfo):
    def utcoffset(self, dt):
        return None


def pem(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


class Identity:
    def __init__(self, key):
        self.key = key
        self.calls = 0

    async def retrieve_for_isolated_service(self, *, run_id, branch):
        self.calls += 1
        assert run_id == "run-12345678"
        assert branch == "feature/test"
        return self.key


class Claims:
    def __init__(self):
        self.used = set()

    async def claim(self, *, release_id, run_id, witness_sha256, now):
        identity = (release_id, run_id, witness_sha256)
        if identity in self.used:
            raise PermissionError("duplicate custody signature")
        self.used.add(identity)


@pytest.mark.asyncio
async def test_custody_is_checked_before_key_access_and_signature_is_verified(monkeypatch):
    key = Ed25519PrivateKey.generate()
    identity = Identity(key)
    now = datetime(2026, 10, 10, tzinfo=UTC)
    verified = VerifiedJenkinsProvenance(
        run_id="run-12345678", branch="feature/test", environment="staging",
        source_commit="a" * 40, source_digest="b" * 64,
        target_digest="c" * 64, started_at=int(now.timestamp()) - 200,
        finished_at=int(now.timestamp()) - 20,
        tests_run=(("notification_worker", 4), ("notification_egress", 3),
                   ("notification_secrets", 2)),
        witness_sha256="d" * 64,
    )
    state = {"fail": True}

    async def readback(*args, **kwargs):
        if state["fail"]:
            assert identity.calls == 0
        if state["fail"]:
            raise ValueError("immutable version unavailable")
        return verified

    monkeypatch.setattr(subject, "load_and_reconcile_witnessed_junit_custody", readback)
    args = dict(
        index_reconciler=object(), report_reconciler=object(), signing_identity=identity, signing_claims=Claims(),
        release_id="release-12345678", run_id="run-12345678",
        branch="feature/test", environment="staging",
        source_commit="a" * 40, source_digest="b" * 64,
        target_digest="c" * 64, witness_public_key_pem=pem(Ed25519PrivateKey.generate()),
        test_signer_public_key_pem=pem(key), witness_issuer="trusted-controller",
        controller_id="jenkins-1", job_full_name="safe/job", now=now,
    )
    with pytest.raises(ValueError, match="immutable version unavailable"):
        await subject.sign_custodied_jenkins_test_result(None, **args)
    assert identity.calls == 0

    state["fail"] = False
    signed = await subject.sign_custodied_jenkins_test_result(None, **args)
    assert identity.calls == 1
    key.public_key().verify(signed.signature, signed.payload)
    payload = json.loads(signed.payload)
    assert payload["purpose"] == "northstar-witnessed-junit-custody"
    assert payload["suites"] == {
        "notification_worker": 4, "notification_egress": 3, "notification_secrets": 2
    }
    assert signed.token().count(".") == 1
    with pytest.raises(PermissionError, match="duplicate"):
        await subject.sign_custodied_jenkins_test_result(None, **args)
    assert identity.calls == 1


@pytest.mark.asyncio
async def test_wrong_key_and_unqualified_suites_fail_closed(monkeypatch):
    key = Ed25519PrivateKey.generate()
    identity = Identity(key)
    now = datetime(2026, 10, 10, tzinfo=UTC)

    async def verified(*args, **kwargs):
        return VerifiedJenkinsProvenance(
            run_id="run-12345678", branch="feature/test", environment="staging",
            source_commit="a" * 40, source_digest="b" * 64,
            target_digest="c" * 64, started_at=int(now.timestamp()) - 50,
            finished_at=int(now.timestamp()) - 10,
            tests_run=(("notification_worker", 1), ("notification_egress", 1),
                       ("notification_egress", 1)),
            witness_sha256="d" * 64,
        )

    monkeypatch.setattr(subject, "load_and_reconcile_witnessed_junit_custody", verified)
    args = dict(
        index_reconciler=object(), report_reconciler=object(), signing_identity=identity, signing_claims=Claims(),
        release_id="release-12345678", run_id="run-12345678",
        branch="feature/test", environment="staging",
        source_commit="a" * 40, source_digest="b" * 64,
        target_digest="c" * 64, witness_public_key_pem=pem(Ed25519PrivateKey.generate()),
        test_signer_public_key_pem=pem(key), witness_issuer="trusted-controller",
        controller_id="jenkins-1", job_full_name="safe/job", now=now,
    )
    with pytest.raises(subject.CustodyAttestationRejected, match="not qualified"):
        await subject.sign_custodied_jenkins_test_result(None, **args)
    assert identity.calls == 0

    async def qualified(*args, **kwargs):
        result = await verified()
        return VerifiedJenkinsProvenance(
            **{**result.__dict__, "tests_run": (
                ("notification_worker", 1), ("notification_egress", 1),
                ("notification_secrets", 1)
            )}
        )

    monkeypatch.setattr(subject, "load_and_reconcile_witnessed_junit_custody", qualified)
    args["test_signer_public_key_pem"] = pem(Ed25519PrivateKey.generate())
    with pytest.raises(subject.CustodyAttestationRejected, match="does not match"):
        await subject.sign_custodied_jenkins_test_result(None, **args)



@pytest.mark.asyncio
@pytest.mark.parametrize("bad_clock", [0, False, "", [], {}, datetime(2026, 10, 10), datetime(2026, 10, 10, tzinfo=NoOffsetTZ())])
async def test_invalid_signing_clock_is_rejected_before_custody_or_key_access(
    monkeypatch, bad_clock
):
    async def no_custody(*args, **kwargs):
        raise AssertionError("invalid clock must never reach custody")

    class NoIdentity:
        async def retrieve_for_isolated_service(self, **kwargs):
            raise AssertionError("invalid clock must never unlock key")

    monkeypatch.setattr(subject, "load_and_reconcile_witnessed_junit_custody", no_custody)
    with pytest.raises(subject.CustodyAttestationRejected, match="timezone-aware"):
        await subject.sign_custodied_jenkins_test_result(
            None,
            index_reconciler=object(),
            report_reconciler=object(),
            signing_identity=NoIdentity(),
            signing_claims=Claims(),
            release_id="release-12345678",
            run_id="run-12345678",
            branch="feature/test",
            environment="staging",
            source_commit="a" * 40,
            source_digest="b" * 64,
            target_digest="c" * 64,
            witness_public_key_pem=b"placeholder",
            test_signer_public_key_pem=pem(Ed25519PrivateKey.generate()),
            witness_issuer="trusted-controller",
            controller_id="jenkins-1",
            job_full_name="safe/job",
            now=bad_clock,
        )
