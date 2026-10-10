"""Offline authorization-to-custody orchestration, not a public API.

Trusted callers must independently authenticate the workload and source the
expected build plan from protected configuration. No deployment is triggered.
"""
from __future__ import annotations

from datetime import UTC, datetime

from .queue_notification_custody_attestation_signer import sign_custodied_jenkins_test_result
from .queue_notification_signing_authorization import (
    ProtectedSigningPlan,
    verify_protected_signing_authorization,
)


async def sign_with_protected_authorization(
    session,
    *,
    authorization_token,
    authorization_public_key_pem,
    authorization_issuer,
    authorization_audience,
    authorization_consumption,
    index_reconciler,
    report_reconciler,
    signing_identity,
    signing_claims,
    release_id,
    run_id,
    branch,
    environment,
    source_commit,
    source_digest,
    target_digest,
    witness_public_key_pem,
    test_signer_public_key_pem,
    witness_issuer,
    controller_id,
    job_full_name,
    now=None,
):
    """Verify authorization, burn its one-time grant, then verify custody."""
    instant = datetime.now(UTC) if now is None else now
    if authorization_consumption is None or signing_claims is None:
        raise PermissionError("committed authorization and signing replay guards are required")
    if not callable(getattr(authorization_consumption, "consume", None)):
        raise PermissionError("authorization consumption service unavailable")
    if not callable(getattr(signing_claims, "claim", None)):
        raise PermissionError("signing claim service unavailable")
    grant_id = verify_protected_signing_authorization(
        authorization_token,
        pinned_issuer_public_key_pem=authorization_public_key_pem,
        expected_issuer=authorization_issuer,
        expected_audience=authorization_audience,
        plan=ProtectedSigningPlan(
            release_id=release_id, run_id=run_id, branch=branch,
            environment=environment, source_commit=source_commit,
            source_digest=source_digest, target_digest=target_digest,
        ),
        now=instant,
    )
    await authorization_consumption.consume(
        authorization_id=grant_id, release_id=release_id,
        run_id=run_id, now=instant,
    )
    return await sign_custodied_jenkins_test_result(
        session, index_reconciler=index_reconciler,
        report_reconciler=report_reconciler,
        signing_identity=signing_identity, signing_claims=signing_claims,
        release_id=release_id, run_id=run_id, branch=branch,
        environment=environment, source_commit=source_commit,
        source_digest=source_digest, target_digest=target_digest,
        witness_public_key_pem=witness_public_key_pem,
        test_signer_public_key_pem=test_signer_public_key_pem,
        witness_issuer=witness_issuer, controller_id=controller_id,
        job_full_name=job_full_name, now=instant,
    )
