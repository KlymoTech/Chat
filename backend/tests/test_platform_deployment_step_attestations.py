"""Independent Ed25519 verifier: wrong key, scope, time or content fail closed."""
import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from northstar_api.modules.platform_runtime.deployment_step_attestations import (
    verify_step_attestation,
)

NOW = datetime(2026, 10, 8, 18, tzinfo=UTC)


def fixture():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fields = {
        "change_id": uuid4(),
        "lease_token": uuid4(),
        "environment": "production",
        "step_index": 0,
        "step_name": "validate_dependencies",
        "source_digest": "a" * 64,
        "target_digest": "b" * 64,
    }
    return private, public, fields


def sign(private, fields, **overrides):
    payload = {
        **{name: str(value) if name in ("change_id", "lease_token") else value
           for name, value in fields.items()},
        "evidence_digest": "c" * 64,
        "verifier_run_id": "independent-verifier-123",
        "issued_at": int((NOW - timedelta(minutes=1)).timestamp()),
        "expires_at": int((NOW + timedelta(minutes=5)).timestamp()),
        **overrides,
    }
    message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    def encode(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    return encode(message) + "." + encode(private.sign(message))


def test_correct_step_is_verified():
    private, public, fields = fixture()
    proof = verify_step_attestation(sign(private, fields), public_key_pem=public, now=NOW, **fields)
    assert proof is not None
    assert proof.evidence_digest == "c" * 64


def test_wrong_signer_or_changed_evidence_rejected():
    private, public, fields = fixture()
    token = sign(private, fields)
    stranger = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    assert verify_step_attestation(token, public_key_pem=stranger, now=NOW, **fields) is None
    payload, signature = token.split(".")
    assert verify_step_attestation(payload + "A." + signature, public_key_pem=public, now=NOW, **fields) is None


def test_wrong_lease_change_step_environment_or_digest_rejected():
    private, public, fields = fixture()
    token = sign(private, fields)
    for override in (
        {"change_id": uuid4()},
        {"lease_token": uuid4()},
        {"step_index": 1},
        {"step_name": "skip_verification"},
        {"environment": "staging"},
        {"target_digest": "0" * 64},
    ):
        actual = dict(fields)
        actual.update(override)
        assert verify_step_attestation(token, public_key_pem=public, now=NOW, **actual) is None


def test_expired_future_or_overlong_proof_rejected():
    private, public, fields = fixture()
    for overrides in (
        {"expires_at": int(NOW.timestamp())},
        {"issued_at": int((NOW + timedelta(minutes=1)).timestamp())},
        {"expires_at": int((NOW + timedelta(hours=4)).timestamp())},
    ):
        assert verify_step_attestation(
            sign(private, fields, **overrides), public_key_pem=public, now=NOW, **fields
        ) is None


def test_unsigned_invalid_or_missing_key_fails_closed():
    private, public, fields = fixture()
    token = sign(private, fields)
    for bad_token in ("", "not.a.valid.token", "unsigned", token + "junk"):
        assert verify_step_attestation(bad_token, public_key_pem=public, now=NOW, **fields) is None
    assert verify_step_attestation(token, public_key_pem=b"invalid", now=NOW, **fields) is None
