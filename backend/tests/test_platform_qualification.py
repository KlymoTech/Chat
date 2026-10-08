"""Qualification proof verification: tampering, expiry and binding fail closed."""
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

from northstar_api.modules.platform_runtime.qualification import verify_qualification_proofs

KEY = b"qualification-isolated-test-key-with-at-least-32-bytes"
SOURCE = "a" * 64
TARGET = "b" * 64


def token(kind="health_snapshot", *, issued=1000, expires=1500, environment="staging",
          source=SOURCE, target=TARGET):
    payload = json.dumps({
        "kind": kind, "environment": environment,
        "source_digest": source, "target_digest": target,
        "run_id": "qual-run-0001", "issued_at": issued, "expires_at": expires,
    }, sort_keys=True).encode()
    digest = hmac.new(KEY, payload, hashlib.sha256).digest()
    def enc(val: bytes) -> str:
        return base64.urlsafe_b64encode(val).decode().rstrip("=")
    return enc(payload) + "." + enc(digest)


def verify(*proofs, key=KEY, required=("health_snapshot",)):
    return verify_qualification_proofs(
        tuple(proofs), required=required, environment="staging",
        source_digest=SOURCE, target_digest=TARGET,
        signing_key=key, now=datetime.fromtimestamp(1200, UTC),
    )


def test_signed_bound_proof_accepted():
    assert verify(token()) == ()


def test_missing_and_tampered_proofs_fail():
    assert verify() == ("missing_verified:health_snapshot",)
    assert verify(token()[:-1] + "x") == ("missing_verified:health_snapshot",)


def test_wrong_environment_or_digest_fails():
    assert verify(token(environment="production")) != ()
    assert verify(token(target="c" * 64)) != ()


def test_expired_and_future_evidence_fails():
    assert verify(token(expires=1100)) != ()
    assert verify(token(issued=1300)) != ()


def test_weak_signing_key_and_missing_kind_fail():
    assert verify(token(), key=b"weak") == ("qualification_key_unavailable",)
    assert verify(token(), required=("backup_restore_proof",)) != ()
