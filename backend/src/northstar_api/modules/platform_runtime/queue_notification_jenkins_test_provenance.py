"""Independent Jenkins run witness and raw JUnit evidence verification.

A test attestation must never be signed based only on caller-provided
"passed" labels. This gate checks a distinct pinned witness signature and
the exact raw JUnit report bytes. It does not fetch artifacts, sign tests,
approve qualifications, or provision Jenkins/AWS resources.

Production witness issuance MUST run outside the attestation signer, under
independent job authorization and immutable artifact-read controls.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

_REQUIRED_SUITES = frozenset({"notification_worker", "notification_egress", "notification_secrets"})
_B64 = re.compile(r"[A-Za-z0-9_-]+\Z")
_REPORT_LIMIT = 131072
_TOKEN_LIMIT = 16384


class JenkinsProvenanceRejected(ValueError):
    """The run witness or independently supplied test artifacts are untrusted."""


class WitnessedSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tests_run: int = Field(ge=1, le=100000)


class WitnessedJenkinsRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[1]
    witness_issuer: str = Field(min_length=8, max_length=128)
    controller_id: str = Field(min_length=8, max_length=128)
    job_full_name: str = Field(min_length=3, max_length=200)
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,39}$")
    branch: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=32)
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: int = Field(ge=1)
    finished_at: int = Field(ge=1)
    suites: dict[str, WitnessedSuite] = Field(min_length=3, max_length=3)


@dataclass(frozen=True)
class VerifiedJenkinsProvenance:
    run_id: str
    branch: str
    environment: str
    source_commit: str
    source_digest: str
    target_digest: str
    started_at: int
    finished_at: int
    tests_run: tuple[tuple[str, int], ...]
    witness_sha256: str


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise JenkinsProvenanceRejected("duplicate witness property")
        result[key] = value
    return result


def _decode(segment: str, *, max_chars: int) -> bytes:
    if not segment or len(segment) > max_chars or _B64.fullmatch(segment) is None:
        raise JenkinsProvenanceRejected("invalid run witness encoding")
    try:
        return base64.b64decode(
            segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise JenkinsProvenanceRejected("invalid witness base64url encoding") from exc


def _junit_count(suite_name: str, report: bytes) -> int:
    if not isinstance(report, bytes) or not 1 <= len(report) <= _REPORT_LIMIT:
        raise JenkinsProvenanceRejected("JUnit artifact missing or oversized")
    # ElementTree does not resolve external entities, but DTD/entity
    # declarations are prohibited entirely in this security boundary.
    upper = report.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise JenkinsProvenanceRejected("DTD and entities prohibited in JUnit")
    try:
        root = ET.fromstring(report)  # noqa: S314 - bounded JUnit, DTD/entity declarations rejected above
        if root.tag != "testsuite" or root.attrib.get("name") != suite_name:
            raise JenkinsProvenanceRejected("unexpected JUnit suite identity")
        values = {name: int(root.attrib[name]) for name in ("tests", "failures", "errors", "skipped")}
        cases = root.findall("testcase")
        if (
            not 1 <= values["tests"] <= 100000
            or any(values[name] != 0 for name in ("failures", "errors", "skipped"))
            or len(cases) != values["tests"]
            or any(not case.attrib.get("name") for case in cases)
            or any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped"))
            or any(node.tag == "testsuite" for node in root)
        ):
            raise JenkinsProvenanceRejected("JUnit tests are missing, failed or skipped")
        return values["tests"]
    except (ET.ParseError, ValueError, KeyError, OverflowError) as exc:
        raise JenkinsProvenanceRejected("invalid JUnit report") from exc


def verify_witnessed_jenkins_reports(
    witness_token: str,
    *,
    witness_public_key_pem: bytes,
    attestation_signer_public_key_pem: bytes,
    witness_issuer: str,
    controller_id: str,
    job_full_name: str,
    run_id: str,
    branch: str,
    environment: str,
    source_commit: str,
    source_digest: str,
    target_digest: str,
    junit_reports: Mapping[str, bytes],
    now: datetime | None = None,
) -> VerifiedJenkinsProvenance:
    """Verify distinct witness authority, exact run, and all JUnit bytes.

    All expected metadata and public keys must be externally pinned to a
    protected build plan; none should be derived from the witness payload.
    """
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise JenkinsProvenanceRejected("timezone-aware verification required")
    if (
        not isinstance(witness_token, str)
        or len(witness_token) > _TOKEN_LIMIT
        or not isinstance(witness_public_key_pem, bytes)
        or not isinstance(attestation_signer_public_key_pem, bytes)
    ):
        raise JenkinsProvenanceRejected("witness or trusted signer unavailable")
    try:
        signed_body, signed_sig = witness_token.split(".")
        body = _decode(signed_body, max_chars=11000)
        signature = _decode(signed_sig, max_chars=128)
        witness_key = serialization.load_pem_public_key(witness_public_key_pem)
        signer_key = serialization.load_pem_public_key(attestation_signer_public_key_pem)
        if (
            not isinstance(witness_key, Ed25519PublicKey)
            or not isinstance(signer_key, Ed25519PublicKey)
            or len(signature) != 64
        ):
            raise JenkinsProvenanceRejected("witness and signer must use independent Ed25519 keys")
        if hmac.compare_digest(
            witness_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
            signer_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
        ):
            raise JenkinsProvenanceRejected("witness key must be independent from signing key")
        witness_key.verify(signature, body)
        observed = WitnessedJenkinsRun.model_validate(
            json.loads(body, object_pairs_hook=_unique_keys)
        )
    except (ValueError, TypeError, InvalidSignature, UnicodeDecodeError) as exc:
        raise JenkinsProvenanceRejected("untrusted Jenkins run witness") from exc

    current = int(instant.astimezone(UTC).timestamp())
    if (
        observed.witness_issuer != witness_issuer
        or observed.controller_id != controller_id
        or observed.job_full_name != job_full_name
        or observed.run_id != run_id
        or observed.branch != branch
        or observed.environment != environment
        or observed.source_commit != source_commit
        or observed.source_digest != source_digest
        or observed.target_digest != target_digest
        or observed.started_at > observed.finished_at
        or observed.finished_at > current
        or current - observed.finished_at > 900
        or observed.finished_at - observed.started_at > 7200
        or frozenset(observed.suites) != _REQUIRED_SUITES
        or not isinstance(junit_reports, Mapping)
        or frozenset(junit_reports) != _REQUIRED_SUITES
    ):
        raise JenkinsProvenanceRejected("Jenkins build identity, freshness or report set mismatch")

    counts: list[tuple[str, int]] = []
    for name in sorted(_REQUIRED_SUITES):
        raw = junit_reports[name]
        count = _junit_count(name, raw)
        if (
            count != observed.suites[name].tests_run
            or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), observed.suites[name].sha256)
        ):
            raise JenkinsProvenanceRejected("JUnit evidence differs from signed witness")
        counts.append((name, count))

    return VerifiedJenkinsProvenance(
        run_id=run_id,
        branch=branch,
        environment=environment,
        source_commit=source_commit,
        source_digest=source_digest,
        target_digest=target_digest,
        started_at=observed.started_at,
        finished_at=observed.finished_at,
        tests_run=tuple(counts),
        witness_sha256=hashlib.sha256(body).hexdigest(),
    )
