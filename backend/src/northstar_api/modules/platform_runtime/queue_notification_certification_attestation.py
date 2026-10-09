"""Independently signed Jenkins test results gate notification qualification proofs.

The test runner owns a distinct Ed25519 signing identity. The credentialed
qualification issuer can retrieve its HMAC key only *after* verification of
fresh, complete, exact-build test evidence. No HTTP route or worker is enabled.
A production deployment must pin the trusted test-runner public key and isolate
both machine roles; caller-provided identity or test status is never proof.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import UTC, datetime
from typing import Literal, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from .queue_notification_qualification_issuer import issue_notification_qualification_proofs
from .queue_notification_worker_qualification import PersistedNotificationWorkerQualification

_REQUIRED = frozenset(PersistedNotificationWorkerQualification.REQUIRED)
_SEGMENT = re.compile(r"[A-Za-z0-9_-]+\Z")


class CertificationAttestationError(ValueError):
    """The supplied certification result is not a trusted release artifact."""


class CertificationSuiteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: Literal["passed", "failed", "skipped", "cancelled"]
    tests_run: int = Field(ge=1)
    tests_failed: int = Field(ge=0)
    tests_skipped: int = Field(ge=0)


class JenkinsCertificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[1]
    issuer: str = Field(min_length=8, max_length=128)
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,39}$")
    branch: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=32)
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: int = Field(ge=1)
    finished_at: int = Field(ge=1)
    suites: dict[str, CertificationSuiteResult] = Field(min_length=3, max_length=3)


class QualificationSigningKeyStore(Protocol):
    async def retrieve(self, *, run_id: str) -> bytes | None: ...


def _segment_decode(value: str, *, limit: int) -> bytes:
    if not value or len(value) > limit or _SEGMENT.fullmatch(value) is None:
        raise CertificationAttestationError("invalid certification attestation")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise CertificationAttestationError("invalid certification attestation") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CertificationAttestationError("duplicate certification field")
        result[key] = value
    return result


def verify_jenkins_certification_result(
    token: str,
    *,
    test_runner_public_key_pem: bytes,
    issuer: str,
    run_id: str,
    branch: str,
    environment: str,
    source_commit: str,
    source_digest: str,
    target_digest: str,
    now: datetime | None = None,
) -> frozenset[str]:
    """Verify exact signed bytes, identity, build and all mandatory passing suites."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise CertificationAttestationError("timezone-aware verification time required")
    if not isinstance(token, str) or len(token) > 16384 or not test_runner_public_key_pem:
        raise CertificationAttestationError("certification result unavailable")
    try:
        encoded, signed = token.split(".")
        message = _segment_decode(encoded, limit=11000)
        signature = _segment_decode(signed, limit=128)
        public_key = serialization.load_pem_public_key(test_runner_public_key_pem)
        if not isinstance(public_key, Ed25519PublicKey) or len(signature) != 64:
            raise CertificationAttestationError("untrusted certification key")
        public_key.verify(signature, message)
        result = JenkinsCertificationResult.model_validate(
            json.loads(message, object_pairs_hook=_reject_duplicate_keys)
        )
    except (ValueError, TypeError, InvalidSignature, UnicodeDecodeError, KeyError) as exc:
        raise CertificationAttestationError("certification verification failed") from exc

    current = int(instant.astimezone(UTC).timestamp())
    if (
        result.issuer != issuer
        or result.run_id != run_id
        or result.branch != branch
        or result.environment != environment
        or result.source_commit != source_commit
        or result.source_digest != source_digest
        or result.target_digest != target_digest
        or result.started_at > result.finished_at
        or result.finished_at > current
        or current - result.finished_at > 900
        or result.finished_at - result.started_at > 7200
        or frozenset(result.suites) != _REQUIRED
        or any(
            suite.status != "passed"
            or suite.tests_failed != 0
            or suite.tests_skipped != 0
            or suite.tests_failed + suite.tests_skipped > suite.tests_run
            for suite in result.suites.values()
        )
    ):
        raise CertificationAttestationError("certification not qualified")
    return _REQUIRED


async def issue_verified_notification_qualification_proofs(
    *,
    attestation_token: str,
    test_runner_public_key_pem: bytes,
    issuer: str,
    run_id: str,
    branch: str,
    environment: str,
    source_commit: str,
    source_digest: str,
    target_digest: str,
    signing_key_store: QualificationSigningKeyStore,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Issue only after independently signed tests AND AWS-pinned issuer identity."""
    checked_at = now or datetime.now(UTC)
    certified = verify_jenkins_certification_result(
        attestation_token,
        test_runner_public_key_pem=test_runner_public_key_pem,
        issuer=issuer,
        run_id=run_id,
        branch=branch,
        environment=environment,
        source_commit=source_commit,
        source_digest=source_digest,
        target_digest=target_digest,
        now=checked_at,
    )
    key = await signing_key_store.retrieve(run_id=run_id)
    if key is None:
        raise PermissionError("qualified issuer signing key unavailable")
    return issue_notification_qualification_proofs(
        environment=environment,
        source_digest=source_digest,
        target_digest=target_digest,
        run_id=run_id,
        signing_key=key,
        certified_kinds=certified,
        certification_passed=True,
        trusted_issuer=True,
        now=checked_at,
    )
