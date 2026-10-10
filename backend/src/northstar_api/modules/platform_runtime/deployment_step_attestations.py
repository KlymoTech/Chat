"""Verify externally signed evidence for one fenced deployment step.

The verifier owns only an Ed25519 PUBLIC key. The private signing key must stay
in the isolated qualification service, never in an API or deployment worker.
No infrastructure mutation and no proof issuance occurs in this module.
"""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class DeploymentStepAttestation(BaseModel):
    """Single-use step evidence, strictly scoped to the currently owned lease."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    change_id: UUID
    lease_token: UUID
    environment: str = Field(min_length=1, max_length=32)
    step_index: int = Field(ge=0)
    step_name: str = Field(min_length=1, max_length=120)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    verifier_run_id: str = Field(min_length=8, max_length=128)
    issued_at: int = Field(ge=1)
    expires_at: int = Field(ge=1)


def _decode(part: str) -> bytes:
    if not part or len(part) > 4096:
        raise ValueError("invalid attestation encoding")
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def verify_step_attestation(
    token: str,
    *,
    public_key_pem: bytes,
    change_id: UUID,
    lease_token: UUID,
    environment: str,
    step_index: int,
    step_name: str,
    source_digest: str,
    target_digest: str,
    now: datetime | None = None,
) -> DeploymentStepAttestation | None:
    """Return independently verified evidence or None; never trust labels alone."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or not token or len(token) > 8192:
        return None
    try:
        encoded, encoded_signature = token.split(".", 1)
        message = _decode(encoded)
        signature = _decode(encoded_signature)
        key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(key, Ed25519PublicKey):
            return None
        key.verify(signature, message)
        proof = DeploymentStepAttestation.model_validate(json.loads(message))
    except (ValueError, TypeError, InvalidSignature, ValidationError, UnicodeDecodeError):
        return None
    if (
        proof.change_id != change_id
        or proof.lease_token != lease_token
        or proof.environment != environment
        or proof.step_index != step_index
        or proof.step_name != step_name
        or proof.source_digest != source_digest
        or proof.target_digest != target_digest
        or proof.issued_at > int(instant.timestamp())
        or proof.expires_at <= int(instant.timestamp())
        or proof.expires_at <= proof.issued_at
        or proof.expires_at - proof.issued_at > 900
    ):
        return None
    return proof
