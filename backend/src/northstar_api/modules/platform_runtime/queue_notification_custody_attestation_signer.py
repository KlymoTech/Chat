"""Custody-first private Ed25519 signing boundary for witnessed Jenkins tests.

This is an internal library, not a REST API or a qualification approval. A
trusted caller must supply the protected build plan and configured public
keys; caller-selected report bytes, S3 versions and signing payloads are not
accepted. The archived witness remains subject to its freshness policy.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy.ext.asyncio import AsyncSession

from .queue_notification_jenkins_junit_custody import (
    JunitEvidenceIndexReconciler,
    load_and_reconcile_witnessed_junit_custody,
)
from .queue_notification_jenkins_test_provenance import VerifiedJenkinsProvenance
from .queue_notification_custody_signing_claims import SigningClaimStore

_REQUIRED_SUITES = frozenset({"notification_worker", "notification_egress", "notification_secrets"})


class CustodyAttestationRejected(ValueError):
    """The protected evidence cannot be certified."""


class PrivateTestSigner(Protocol):
    async def retrieve_for_isolated_service(
        self, *, run_id: str, branch: str
    ) -> Ed25519PrivateKey | None: ...


@dataclass(frozen=True)
class SignedCustodyAttestation:
    payload: bytes
    signature: bytes

    def token(self) -> str:
        def encode(data):
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
        return encode(self.payload) + "." + encode(self.signature)


async def sign_custodied_jenkins_test_result(
    session: AsyncSession,
    *,
    index_reconciler: JunitEvidenceIndexReconciler,
    report_reconciler: object,
    signing_identity: PrivateTestSigner,
    signing_claims: SigningClaimStore,
    release_id: str,
    run_id: str,
    branch: str,
    environment: str,
    source_commit: str,
    source_digest: str,
    target_digest: str,
    witness_public_key_pem: bytes,
    test_signer_public_key_pem: bytes,
    witness_issuer: str,
    controller_id: str,
    job_full_name: str,
    now: datetime | None = None,
) -> SignedCustodyAttestation:
    """Read immutable custody, reverify S3, THEN unlock the protected key.

    The output is evidence only: no proof ingestion, release approval, worker
    start, HTTP endpoint, cloud mutation, or database commit is performed.
    """
    instant = datetime.now(UTC) if now is None else now
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise CustodyAttestationRejected("timezone-aware signing time required")
    try:
        trusted = serialization.load_pem_public_key(test_signer_public_key_pem)
    except (TypeError, ValueError) as exc:
        raise CustodyAttestationRejected("invalid pinned test signer") from exc
    if not isinstance(trusted, Ed25519PublicKey):
        raise CustodyAttestationRejected("pinned test signer must use Ed25519")
    verified = await load_and_reconcile_witnessed_junit_custody(
        session,
        index_reconciler=index_reconciler,
        report_reconciler=report_reconciler,
        release_id=release_id,
        run_id=run_id,
        branch=branch,
        environment=environment,
        source_commit=source_commit,
        source_digest=source_digest,
        target_digest=target_digest,
        witness_public_key_pem=witness_public_key_pem,
        attestation_signer_public_key_pem=test_signer_public_key_pem,
        witness_issuer=witness_issuer,
        controller_id=controller_id,
        job_full_name=job_full_name,
        now=instant,
    )
    if not isinstance(verified, VerifiedJenkinsProvenance):
        raise CustodyAttestationRejected("missing independently verified evidence")
    counts = verified.tests_run
    if (
        verified.run_id != run_id
        or verified.branch != branch
        or verified.environment != environment
        or verified.source_commit != source_commit
        or verified.source_digest != source_digest
        or verified.target_digest != target_digest
        or not isinstance(counts, tuple)
        or len(counts) != 3
        or any(
            not isinstance(item, tuple) or len(item) != 2
            or not isinstance(item[0], str)
            or type(item[1]) is not int or item[1] < 1
            for item in counts
        )
        or frozenset(name for name, _ in counts) != _REQUIRED_SUITES
        or type(verified.started_at) is not int
        or type(verified.finished_at) is not int
        or verified.started_at > verified.finished_at
        or verified.finished_at > int(instant.timestamp())
        or int(instant.timestamp()) - verified.finished_at > 900
    ):
        raise CustodyAttestationRejected("custodied tests are not qualified")
    # Construct content solely from the verified, protected record.
    statement = {
        "version": 1,
        "purpose": "northstar-witnessed-junit-custody",
        "release_id": release_id,
        "run_id": verified.run_id,
        "branch": verified.branch,
        "environment": verified.environment,
        "source_commit": verified.source_commit,
        "source_digest": verified.source_digest,
        "target_digest": verified.target_digest,
        "witness_sha256": verified.witness_sha256,
        "started_at": verified.started_at,
        "finished_at": verified.finished_at,
        "suites": {name: count for name, count in sorted(counts)},
    }
    payload = json.dumps(statement, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    if signing_claims is None:
        raise PermissionError("durable signing replay guard required")
    # A separate committed transaction must succeed before key retrieval.
    # A crash after this point burns the claim and requires a new approved run.
    await signing_claims.claim(
        release_id=release_id, run_id=run_id,
        witness_sha256=verified.witness_sha256, now=instant,
    )
    key = await signing_identity.retrieve_for_isolated_service(run_id=run_id, branch=branch)
    if not isinstance(key, Ed25519PrivateKey):
        raise PermissionError("protected test signer unavailable")
    if key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ) != trusted.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw):
        raise CustodyAttestationRejected("protected signing identity does not match pinned key")
    signature = key.sign(payload)
    try:
        trusted.verify(signature, payload)
    except InvalidSignature as exc:
        raise CustodyAttestationRejected("signed evidence failed self-verification") from exc
    return SignedCustodyAttestation(payload=payload, signature=signature)
