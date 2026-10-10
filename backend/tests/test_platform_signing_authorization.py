"""Offline Ed25519 authorization checks: exact build and no caller override."""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.queue_notification_signing_authorization import (
    ProtectedSigningPlan, SigningAuthorizationRejected,
    verify_protected_signing_authorization,
)


def _token(key, plan, at, **changes):
    body = dict(
        version=1, issuer="protected-issuer", audience="private-test-signer",
        purpose="sign-witnessed-junit-custody", authorization_id="issuer-once-12345678",
        release_id=plan.release_id, run_id=plan.run_id, branch=plan.branch,
        environment=plan.environment, source_commit=plan.source_commit,
        source_digest=plan.source_digest, target_digest=plan.target_digest,
        issued_at=int(at.timestamp()), expires_at=int(at.timestamp()) + 120,
    )
    body.update(changes)
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    def enc(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
    return enc(payload) + "." + enc(key.sign(payload))


def _fixture():
    key = Ed25519PrivateKey.generate()
    at = datetime(2026, 10, 10, 10, tzinfo=UTC)
    plan = ProtectedSigningPlan(
        release_id="release-12345678", run_id="run-12345678",
        branch="feature/northstar", environment="staging",
        source_commit="a" * 40, source_digest="b" * 64, target_digest="c" * 64,
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return key, at, plan, public


def test_exact_signing_authorization_accepts_pinned_build():
    key, at, plan, public = _fixture()
    result = verify_protected_signing_authorization(
        _token(key, plan, at), pinned_issuer_public_key_pem=public,
        expected_issuer="protected-issuer", expected_audience="private-test-signer",
        plan=plan, now=at,
    )
    assert result == "issuer-once-12345678"


@pytest.mark.parametrize("change", [
    {"environment": "production"}, {"branch": "main"},
    {"run_id": "other-run-123456"}, {"source_digest": "d" * 64},
    {"purpose": "start-worker"}, {"audience": "public-api"},
    {"authorization_id": "short"}, {"expires_at": 1},
    {"version": True}, {"issued_at": "yesterday"},
])
def test_signed_but_unauthorized_requests_fail(change):
    key, at, plan, public = _fixture()
    with pytest.raises(SigningAuthorizationRejected):
        verify_protected_signing_authorization(
            _token(key, plan, at, **change), pinned_issuer_public_key_pem=public,
            expected_issuer="protected-issuer", expected_audience="private-test-signer",
            plan=plan, now=at,
        )


def test_wrong_key_and_expired_authorization_fail():
    key, at, plan, public = _fixture()
    token = _token(key, plan, at)
    for pinned, instant in (
        (Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ), at),
        (public, at + timedelta(minutes=6)),
    ):
        with pytest.raises(SigningAuthorizationRejected):
            verify_protected_signing_authorization(
                token, pinned_issuer_public_key_pem=pinned,
                expected_issuer="protected-issuer", expected_audience="private-test-signer",
                plan=plan, now=instant,
            )


def test_duplicate_json_fields_and_noncanonical_tokens_fail():
    key, at, plan, public = _fixture()
    valid = _token(key, plan, at)
    payload_segment, _ = valid.split(".")
    payload = base64.urlsafe_b64decode(payload_segment + "=" * (-len(payload_segment) % 4))
    tampered = payload[:-1] + b',"environment":"production"}'
    # The duplicate key is inside a signed, syntactically valid JSON object.
    assert json.loads(tampered)["environment"] == "production"
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
    malformed = encode(tampered) + "." + encode(key.sign(tampered))
    for token in (malformed, valid + "=", valid + ".suffix", "invalid"):
        with pytest.raises(SigningAuthorizationRejected):
            verify_protected_signing_authorization(
                token, pinned_issuer_public_key_pem=public,
                expected_issuer="protected-issuer",
                expected_audience="private-test-signer",
                plan=plan, now=at,
            )


def test_missing_expected_issuer_signature_rejected():
    key, at, plan, public = _fixture()
    with pytest.raises(SigningAuthorizationRejected):
        verify_protected_signing_authorization(
            _token(key, plan, at, issuer="wrong-issuer"),
            pinned_issuer_public_key_pem=public,
            expected_issuer="protected-issuer",
            expected_audience="private-test-signer",
            plan=plan, now=at,
        )


@pytest.mark.parametrize("change", [
    {"release_id": 123}, {"run_id": None}, {"branch": True},
    {"source_commit": ["a" * 40]}, {"target_digest": {"value": "c" * 64}},
    {"issuer": ["protected-issuer"]}, {"audience": None},
])
def test_signed_authorization_with_wrong_field_types_is_rejected(change):
    key, at, plan, public = _fixture()
    with pytest.raises(SigningAuthorizationRejected):
        verify_protected_signing_authorization(
            _token(key, plan, at, **change),
            pinned_issuer_public_key_pem=public,
            expected_issuer="protected-issuer",
            expected_audience="private-test-signer",
            plan=plan, now=at,
        )


def test_invalid_signing_clock_fails_closed():
    key, at, plan, public = _fixture()
    with pytest.raises(SigningAuthorizationRejected, match="timezone-aware"):
        verify_protected_signing_authorization(
            _token(key, plan, at),
            pinned_issuer_public_key_pem=public,
            expected_issuer="protected-issuer",
            expected_audience="private-test-signer",
            plan=plan, now="invalid",
        )



@pytest.mark.parametrize("bad_clock", [0, False, "", [], {}])
def test_falsey_clock_never_falls_back_to_current_time(bad_clock):
    key, at, plan, public = _fixture()
    with pytest.raises(SigningAuthorizationRejected, match="timezone-aware"):
        verify_protected_signing_authorization(
            _token(key, plan, at),
            pinned_issuer_public_key_pem=public,
            expected_issuer="protected-issuer",
            expected_audience="private-test-signer",
            plan=plan,
            now=bad_clock,
        )



@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_signed_nonstandard_json_constants_are_rejected(constant):
    key, at, plan, public = _fixture()
    token = _token(key, plan, at)
    body_segment, _ = token.split(".")
    body = base64.urlsafe_b64decode(body_segment + "=" * (-len(body_segment) % 4))
    amended = body[:-1] + b',"extra":' + constant.encode("ascii") + b"}"
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
    signed = encode(amended) + "." + encode(key.sign(amended))
    with pytest.raises(SigningAuthorizationRejected):
        verify_protected_signing_authorization(
            signed, pinned_issuer_public_key_pem=public,
            expected_issuer="protected-issuer",
            expected_audience="private-test-signer", plan=plan, now=at,
        )
