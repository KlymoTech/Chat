"""Offline, pinned Ed25519 authorization for an isolated signing invocation.

This verifies a separately issued job authorization, NOT runtime workload
identity, mTLS, an AWS principal, or permission to deploy. The signing service
must independently establish those properties at its private boundary.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_B64 = re.compile(r"[A-Za-z0-9_-]+\Z")


class SigningAuthorizationRejected(PermissionError):
    """No trusted authorization for the exact signing operation."""


@dataclass(frozen=True)
class ProtectedSigningPlan:
    release_id: str
    run_id: str
    branch: str
    environment: str
    source_commit: str
    source_digest: str
    target_digest: str


def _decode(value: str, maximum: int) -> bytes:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or not _B64.fullmatch(value):
        raise SigningAuthorizationRejected("invalid signing authorization")
    try:
        result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SigningAuthorizationRejected("invalid signing authorization") from exc
    if base64.urlsafe_b64encode(result).rstrip(b"=").decode("ascii") != value:
        raise SigningAuthorizationRejected("noncanonical signing authorization")
    return result


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SigningAuthorizationRejected("duplicate signing authorization property")
        result[key] = value
    return result


def verify_protected_signing_authorization(
    token: str, *, pinned_issuer_public_key_pem: bytes,
    expected_issuer: str, expected_audience: str, plan: ProtectedSigningPlan,
    now: datetime | None = None,
) -> str:
    """Verify the signed exact run, branch, environment and operation scope.

    The result is the one-time authorization ID; production must also persist
    an independently enforced replay decision before key retrieval.
    """
    instant = now or datetime.now(UTC)
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise SigningAuthorizationRejected("timezone-aware authorization required")
    if not isinstance(token, str) or len(token) > 4096 or token.count(".") != 1:
        raise SigningAuthorizationRejected("invalid authorization token")
    try:
        body_segment, signature_segment = token.split(".")
        body = _decode(body_segment, 3000)
        signature = _decode(signature_segment, 100)
        public = serialization.load_pem_public_key(pinned_issuer_public_key_pem)
        if not isinstance(public, Ed25519PublicKey) or len(signature) != 64:
            raise SigningAuthorizationRejected("invalid authorization signer")
        public.verify(signature, body)
        statement = json.loads(body, object_pairs_hook=_unique)
    except (TypeError, ValueError, InvalidSignature, UnicodeDecodeError) as exc:
        raise SigningAuthorizationRejected("signing authorization not verified") from exc

    if not isinstance(statement, dict):
        raise SigningAuthorizationRejected("invalid authorization statement")
    required = {
        "version", "issuer", "audience", "purpose", "authorization_id",
        "release_id", "run_id", "branch", "environment", "source_commit",
        "source_digest", "target_digest", "issued_at", "expires_at",
    }
    if set(statement) != required:
        raise SigningAuthorizationRejected("authorization fields do not match")
    current = int(instant.astimezone(UTC).timestamp())
    issued, expires = statement["issued_at"], statement["expires_at"]
    auth_id = statement["authorization_id"]
    if (
        type(statement["version"]) is not int or statement["version"] != 1
        or type(statement["issuer"]) is not str
        or type(statement["audience"]) is not str
        or statement["issuer"] != expected_issuer
        or statement["audience"] != expected_audience
        or statement["purpose"] != "sign-witnessed-junit-custody"
        or type(auth_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", auth_id)
        or any(type(statement[key]) is not str or not statement[key] for key in (
            "release_id", "run_id", "branch", "environment", "source_commit",
            "source_digest", "target_digest"
        ))
        or type(issued) is not int or type(expires) is not int
        or issued > current or current >= expires or expires - issued > 300
        or issued < current - 300
        or any(statement[key] != getattr(plan, key) for key in (
            "release_id", "run_id", "branch", "environment", "source_commit",
            "source_digest", "target_digest"
        ))
    ):
        raise SigningAuthorizationRejected("signing operation not authorized")
    return auth_id
