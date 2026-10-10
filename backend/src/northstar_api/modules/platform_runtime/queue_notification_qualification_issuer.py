"""Offline certification proof issuer for an isolated, trusted Jenkins controller.

This module has no HTTP endpoint, secret-store access, worker-start capability,
or automatic pipeline invocation. Only a separately authorized certification
runner may supply a protected signing key after independent tests pass.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

from .qualification import QualificationProof, verify_qualification_proofs
from .queue_notification_worker_qualification import PersistedNotificationWorkerQualification


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def issue_notification_qualification_proofs(
    *,
    environment: str,
    source_digest: str,
    target_digest: str,
    run_id: str,
    signing_key: bytes,
    certified_kinds: frozenset[str],
    certification_passed: bool,
    trusted_issuer: bool,
    now: datetime | None = None,
    lifetime_seconds: int = 900,
) -> tuple[str, ...]:
    """Issue short-lived signed proofs only after externally verified certification.

    A caller-supplied boolean is NOT an authentication or build attestation;
    protected Jenkins identity, job policies, and persisted test provenance
    must independently establish both trust decisions before calling.
    """
    required = frozenset(PersistedNotificationWorkerQualification.REQUIRED)
    if not trusted_issuer:
        raise PermissionError("trusted isolated qualification issuer required")
    if not certification_passed or certified_kinds != required:
        raise ValueError("all mandatory qualification checks must pass")
    if len(signing_key) < 32:
        raise ValueError("qualification signing key unavailable")
    if not 60 <= lifetime_seconds <= 3600:
        raise ValueError("proof lifetime outside qualification bounds")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("qualification time must be timezone-aware")
    issued = int(current.astimezone(UTC).timestamp())
    tokens: list[str] = []
    for kind in sorted(required):
        proof = QualificationProof(
            kind=kind, environment=environment,
            source_digest=source_digest, target_digest=target_digest,
            run_id=run_id, issued_at=issued,
            expires_at=issued + lifetime_seconds,
        )
        message = json.dumps(
            proof.model_dump(), separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        signature = hmac.new(signing_key, message, hashlib.sha256).digest()
        tokens.append(_b64(message) + "." + _b64(signature))
    blockers = verify_qualification_proofs(
        tuple(tokens), required=tuple(sorted(required)),
        environment=environment, source_digest=source_digest,
        target_digest=target_digest, signing_key=signing_key,
        now=current,
    )
    if blockers:
        raise ValueError("qualification self-verification failed")
    return tuple(tokens)
