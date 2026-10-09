"""Independently signed release manifest, bound to the exact certified artifact.

No approval, AWS mutation or notification-worker startup is performed here.
The expected release coordinates MUST come from a protected deployment plan,
not from the manifest or a tenant/user request. The release-signing public key
must be independently pinned and rotated by the release control plane.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from .aws_immutable_certification_artifact_store import CertificationArtifactReceipt

_SEGMENT = re.compile(r"[A-Za-z0-9_-]+\Z")
_RELEASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,79}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{7,39}\Z")
_MAX_TOKEN = 16384


class ReleaseManifestRejected(ValueError):
    """Release identity, signed payload or immutable evidence does not qualify."""


class ManifestArtifactReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    bucket: str = Field(min_length=3, max_length=63)
    key: str = Field(min_length=1, max_length=512)
    version_id: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SignedReleaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[1]
    issuer: str = Field(min_length=8, max_length=128)
    release_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,79}$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,39}$")
    branch: str = Field(min_length=1, max_length=200)
    environment: str = Field(min_length=1, max_length=32)
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    attestation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issued_at: int = Field(ge=1)
    artifact: ManifestArtifactReceipt


@dataclass(frozen=True)
class VerifiedReleaseManifest:
    release_id: str
    source_commit: str
    image_digest: str
    environment: str
    manifest_sha256: str
    artifact: CertificationArtifactReceipt


class ArtifactReconciler(Protocol):
    async def reconcile(self, **kwargs: object) -> CertificationArtifactReceipt: ...


def _unique_json(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseManifestRejected("duplicate release manifest field")
        result[key] = value
    return result


def _unpack(segment: str, *, maximum: int) -> bytes:
    if not segment or len(segment) > maximum or _SEGMENT.fullmatch(segment) is None:
        raise ReleaseManifestRejected("invalid signed release manifest")
    try:
        return base64.b64decode(
            segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as exc:
        raise ReleaseManifestRejected("invalid release manifest encoding") from exc


def verify_signed_release_manifest(
    token: str, *,
    release_signer_public_key_pem: bytes,
    trusted_issuer: str,
    release_id: str,
    run_id: str,
    branch: str,
    environment: str,
    source_commit: str,
    image_digest: str,
    source_digest: str,
    target_digest: str,
    attestation_token: str,
    artifact_receipt: CertificationArtifactReceipt,
    now: datetime | None = None,
) -> VerifiedReleaseManifest:
    """Validate signature and all immutable, externally expected coordinates."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ReleaseManifestRejected("timezone-aware verification time required")
    if (
        not isinstance(token, str) or len(token) > _MAX_TOKEN
        or not isinstance(release_signer_public_key_pem, bytes)
        or not release_signer_public_key_pem
        or not _RELEASE.fullmatch(release_id)
        or not _RUN.fullmatch(run_id)
    ):
        raise ReleaseManifestRejected("release manifest unavailable")
    try:
        encoded, signature = token.split(".")
        body = _unpack(encoded, maximum=11000)
        signed = _unpack(signature, maximum=128)
        signer = serialization.load_pem_public_key(release_signer_public_key_pem)
        if not isinstance(signer, Ed25519PublicKey) or len(signed) != 64:
            raise ReleaseManifestRejected("untrusted release signer")
        signer.verify(signed, body)
        manifest = SignedReleaseManifest.model_validate(
            json.loads(body, object_pairs_hook=_unique_json)
        )
    except (ValueError, TypeError, InvalidSignature, UnicodeDecodeError) as exc:
        raise ReleaseManifestRejected("release manifest signature or schema invalid") from exc

    timestamp = int(instant.astimezone(UTC).timestamp())
    expected_key = (
        f"evidence/{release_id}/jenkins/{run_id}/certification-attestation.token"
    )
    digest = hashlib.sha256(attestation_token.encode("utf-8")).hexdigest()
    if (
        manifest.issuer != trusted_issuer
        or manifest.release_id != release_id
        or manifest.run_id != run_id
        or manifest.branch != branch
        or manifest.environment != environment
        or manifest.source_commit != source_commit
        or manifest.image_digest != image_digest
        or manifest.source_digest != source_digest
        or manifest.target_digest != target_digest
        or manifest.attestation_sha256 != digest
        or manifest.artifact.bucket != artifact_receipt.bucket
        or manifest.artifact.key != artifact_receipt.key
        or manifest.artifact.version_id != artifact_receipt.version_id
        or manifest.artifact.sha256 != artifact_receipt.sha256
        or manifest.artifact.key != expected_key
        or manifest.attestation_sha256 != artifact_receipt.sha256
        or manifest.issued_at > timestamp
        or timestamp - manifest.issued_at > 900
    ):
        raise ReleaseManifestRejected("release manifest does not match trusted deployment evidence")
    return VerifiedReleaseManifest(
        release_id=release_id,
        source_commit=source_commit,
        image_digest=image_digest,
        environment=environment,
        manifest_sha256=hashlib.sha256(body).hexdigest(),
        artifact=artifact_receipt,
    )


async def verify_manifest_and_reconcile_artifact(
    token: str, *,
    reconciler: ArtifactReconciler,
    test_runner_public_key_pem: bytes,
    attestation_issuer: str,
    **expected: object,
) -> VerifiedReleaseManifest:
    """Allow S3 read-back only after signed release-manifest validation.

    Never writes or retries unknown S3 outcomes; read errors propagate.
    """
    verified = verify_signed_release_manifest(token, **expected)
    await reconciler.reconcile(
        receipt=verified.artifact,
        release_id=verified.release_id,
        attestation_token=expected["attestation_token"],
        test_runner_public_key_pem=test_runner_public_key_pem,
        issuer=attestation_issuer,
        run_id=expected["run_id"],
        branch=expected["branch"],
        environment=expected["environment"],
        source_commit=verified.source_commit,
        source_digest=expected["source_digest"],
        target_digest=expected["target_digest"],
        now=expected.get("now"),
    )
    return verified
