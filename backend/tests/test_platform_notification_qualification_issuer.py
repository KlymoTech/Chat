"""Offline issuer proofs match the existing runtime verifier."""
from datetime import UTC, datetime, timedelta

import pytest

from northstar_api.modules.platform_runtime.qualification import verify_qualification_proofs
from northstar_api.modules.platform_runtime.queue_notification_qualification_issuer import (
    issue_notification_qualification_proofs,
)
from northstar_api.modules.platform_runtime.queue_notification_worker_qualification import (
    PersistedNotificationWorkerQualification,
)

KEY = b"q" * 32
REQUIRED = frozenset(PersistedNotificationWorkerQualification.REQUIRED)
NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def issue(**overrides):
    kwargs = {
        "environment": "staging", "source_digest": "a" * 64,
        "target_digest": "b" * 64, "run_id": "jenkins-run-123",
        "signing_key": KEY, "certified_kinds": REQUIRED,
        "certification_passed": True, "trusted_issuer": True, "now": NOW,
    }
    kwargs.update(overrides)
    return issue_notification_qualification_proofs(**kwargs)


def test_valid_proofs_are_runtime_verifiable_and_expire():
    tokens = issue()
    assert len(tokens) == 3
    assert not verify_qualification_proofs(
        tokens, required=tuple(sorted(REQUIRED)), environment="staging",
        source_digest="a" * 64, target_digest="b" * 64,
        signing_key=KEY, now=NOW,
    )
    assert verify_qualification_proofs(
        tokens, required=tuple(sorted(REQUIRED)), environment="staging",
        source_digest="a" * 64, target_digest="b" * 64,
        signing_key=KEY, now=NOW + timedelta(minutes=16),
    )


@pytest.mark.parametrize("changes,error", [
    ({"trusted_issuer": False}, PermissionError),
    ({"certification_passed": False}, ValueError),
    ({"certified_kinds": frozenset({"notification_worker"})}, ValueError),
    ({"signing_key": b"weak"}, ValueError),
    ({"lifetime_seconds": 86401}, ValueError),
    ({"source_digest": "invalid"}, ValueError),
])
def test_fail_closed_issuance(changes, error):
    with pytest.raises(error):
        issue(**changes)


def test_proof_rejected_for_other_environment_digest_or_key():
    tokens = issue()
    for environment, digest, key in (
        ("production", "a" * 64, KEY),
        ("staging", "c" * 64, KEY),
        ("staging", "a" * 64, b"w" * 32),
    ):
        assert verify_qualification_proofs(
            tokens, required=tuple(sorted(REQUIRED)),
            environment=environment, source_digest=digest,
            target_digest="b" * 64, signing_key=key, now=NOW,
        )
