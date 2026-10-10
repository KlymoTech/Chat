"""Offline cryptographic integration of authorization, replay and custody signing."""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime import (
    queue_notification_authorized_signing as orchestration,
    queue_notification_custody_attestation_signer as custody_signer,
)
from northstar_api.modules.platform_runtime.queue_notification_jenkins_test_provenance import (
    VerifiedJenkinsProvenance,
)

NOW = datetime(2026, 10, 10, 10, tzinfo=UTC)


def pem(key):
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def authorization_token(key, *, branch="feature/test"):
    statement = {
        "version": 1,
        "issuer": "trusted-offline-controller",
        "audience": "private-test-signer",
        "purpose": "sign-witnessed-junit-custody",
        "authorization_id": "independent-grant-12345678",
        "release_id": "release-12345678",
        "run_id": "run-12345678",
        "branch": branch,
        "environment": "staging",
        "source_commit": "a" * 40,
        "source_digest": "b" * 64,
        "target_digest": "c" * 64,
        "issued_at": int(NOW.timestamp()),
        "expires_at": int(NOW.timestamp()) + 120,
    }
    payload = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode()
    return encoded(payload) + "." + encoded(key.sign(payload))


class AuthorizationLedger:
    def __init__(self):
        self.used = set()

    async def consume(self, *, authorization_id, release_id, run_id, now):
        item = (authorization_id, release_id, run_id)
        if item in self.used:
            raise PermissionError("one-use authorization consumed")
        self.used.add(item)


class SigningLedger:
    def __init__(self):
        self.used = set()

    async def claim(self, *, release_id, run_id, witness_sha256, now):
        item = (release_id, run_id, witness_sha256)
        if item in self.used:
            raise PermissionError("custody signing already claimed")
        self.used.add(item)


class ProtectedIdentity:
    def __init__(self, private_key):
        self.private_key = private_key
        self.calls = 0

    async def retrieve_for_isolated_service(self, *, run_id, branch):
        self.calls += 1
        return self.private_key


@pytest.fixture
def integrated_signing(monkeypatch):
    controller = Ed25519PrivateKey.generate()
    signer = Ed25519PrivateKey.generate()
    witness = Ed25519PrivateKey.generate()
    authorization_ledger = AuthorizationLedger()
    signing_ledger = SigningLedger()
    identity = ProtectedIdentity(signer)
    state = {"custody_reads": 0}

    async def custody_readback(*args, **kwargs):
        state["custody_reads"] += 1
        return VerifiedJenkinsProvenance(
            run_id="run-12345678",
            branch="feature/test",
            environment="staging",
            source_commit="a" * 40,
            source_digest="b" * 64,
            target_digest="c" * 64,
            started_at=int(NOW.timestamp()) - 120,
            finished_at=int(NOW.timestamp()) - 10,
            tests_run=(
                ("notification_worker", 3),
                ("notification_egress", 2),
                ("notification_secrets", 1),
            ),
            witness_sha256="d" * 64,
        )

    monkeypatch.setattr(
        custody_signer, "load_and_reconcile_witnessed_junit_custody", custody_readback,
    )
    monkeypatch.setattr(
        orchestration, "CommittedAuthorizationConsumption", AuthorizationLedger,
    )
    monkeypatch.setattr(
        orchestration, "CommittedPostgresSigningClaims", SigningLedger,
    )
    params = {
        "authorization_token": authorization_token(controller),
        "authorization_public_key_pem": pem(controller),
        "authorization_issuer": "trusted-offline-controller",
        "authorization_audience": "private-test-signer",
        "authorization_consumption": authorization_ledger,
        "index_reconciler": object(),
        "report_reconciler": object(),
        "signing_identity": identity,
        "signing_claims": signing_ledger,
        "release_id": "release-12345678",
        "run_id": "run-12345678",
        "branch": "feature/test",
        "environment": "staging",
        "source_commit": "a" * 40,
        "source_digest": "b" * 64,
        "target_digest": "c" * 64,
        "witness_public_key_pem": pem(witness),
        "test_signer_public_key_pem": pem(signer),
        "witness_issuer": "trusted-controller",
        "controller_id": "jenkins-1",
        "job_full_name": "safe/job",
        "now": NOW,
    }
    return params, state, identity, signer, controller, authorization_ledger, signing_ledger


@pytest.mark.asyncio
async def test_real_ed25519_authorization_and_custody_are_one_use(integrated_signing):
    params, state, identity, signer, _, authorizations, claims = integrated_signing
    attestation = await orchestration.sign_with_protected_authorization(None, **params)
    signer.public_key().verify(attestation.signature, attestation.payload)
    body = json.loads(attestation.payload)
    assert body["purpose"] == "northstar-witnessed-junit-custody"
    assert body["witness_sha256"] == "d" * 64
    assert body["suites"] == {
        "notification_worker": 3,
        "notification_egress": 2,
        "notification_secrets": 1,
    }
    assert len(authorizations.used) == len(claims.used) == 1
    assert identity.calls == state["custody_reads"] == 1
    with pytest.raises(PermissionError, match="consumed"):
        await orchestration.sign_with_protected_authorization(None, **params)
    assert identity.calls == state["custody_reads"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["wrong_branch", "wrong_signer", "wrong_audience"])
async def test_real_authorization_rejection_precedes_custody_and_key_access(
    integrated_signing, tamper
):
    params, state, identity, _, controller, authorizations, claims = integrated_signing
    if tamper == "wrong_branch":
        params["authorization_token"] = authorization_token(
            controller, branch="feature/other",
        )
    elif tamper == "wrong_signer":
        params["authorization_token"] = authorization_token(Ed25519PrivateKey.generate())
    else:
        params["authorization_audience"] = "public-api"
    with pytest.raises(PermissionError):
        await orchestration.sign_with_protected_authorization(None, **params)
    assert authorizations.used == claims.used == set()
    assert identity.calls == state["custody_reads"] == 0
