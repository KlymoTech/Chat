"""Verify externally issued, short-lived qualification evidence.

No API in this module issues proof tokens. The isolated qualification pipeline
must own a distinct signing key. Tokens are bound to environment, both spec
digests and one evidence kind; a user-supplied label is never proof.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QualificationProof(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=3, max_length=80, pattern=r"^[a-z][a-z0-9_]+$")
    environment: str = Field(min_length=1, max_length=32)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str = Field(min_length=8, max_length=128)
    issued_at: int = Field(ge=0)
    expires_at: int = Field(ge=1)


def _decode(segment: str) -> bytes:
    if not segment or len(segment) > 4096:
        raise ValueError("invalid proof encoding")
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def verify_qualification_proofs(
    tokens: tuple[str, ...],
    *,
    required: tuple[str, ...],
    environment: str,
    source_digest: str,
    target_digest: str,
    signing_key: bytes,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Return blockers; invalid, stale or mismatched tokens never authorize work."""
    if len(signing_key) < 32:
        return ("qualification_key_unavailable",)
    instant = int((now or datetime.now(UTC)).timestamp())
    valid: set[str] = set()
    for token in tokens:
        try:
            if len(token) > 8192:
                continue
            encoded, signature = token.split(".", 1)
            message = _decode(encoded)
            supplied_sig = _decode(signature)
            expected_sig = hmac.new(signing_key, message, hashlib.sha256).digest()
            if not hmac.compare_digest(supplied_sig, expected_sig):
                continue
            data: Any = json.loads(message)
            proof = QualificationProof.model_validate(data)
            if (
                proof.environment != environment
                or proof.source_digest != source_digest
                or proof.target_digest != target_digest
                or proof.issued_at > instant
                or proof.expires_at <= instant
                or proof.expires_at - proof.issued_at > 86400
            ):
                continue
            valid.add(proof.kind)
        except (ValueError, TypeError, UnicodeDecodeError, KeyError):
            continue
    return tuple(f"missing_verified:{kind}" for kind in required if kind not in valid)


__all__ = ["QualificationProof", "verify_qualification_proofs"]
