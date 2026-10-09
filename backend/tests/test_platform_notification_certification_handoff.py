"""Signed Jenkins evidence enters governance only as an unapproved pending record."""
import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.exc import IntegrityError

from northstar_api.modules.platform_runtime.queue_notification_certification_attestation import (
    CertificationAttestationError,
)
from northstar_api.modules.platform_runtime.queue_notification_certification_handoff import (
    PendingNotificationQualification,
    stage_verified_notification_qualification,
)
from northstar_api.modules.platform_runtime.queue_notification_worker_qualification import (
    PersistedNotificationWorkerQualification,
)

RUN = "jenkins-build-123"
BRANCH = "feature/northstar-adaptive-architecture-20261008"
SOURCE = "a" * 64
TARGET = "b" * 64
COMMIT = "c" * 40
ISSUER = "northstar-isolated-test-runner"
KEY = b"q" * 32


def signed_result(private_key, *, changes=None):
    instant = datetime.now(UTC)
    report = {
        "version": 1,
        "issuer": ISSUER,
        "run_id": RUN,
        "branch": BRANCH,
        "environment": "staging",
        "source_commit": COMMIT,
        "source_digest": SOURCE,
        "target_digest": TARGET,
        "started_at": int((instant - timedelta(minutes=2)).timestamp()),
        "finished_at": int((instant - timedelta(seconds=5)).timestamp()),
        "suites": {
            kind: {
                "status": "passed", "tests_run": 6, "tests_failed": 0,
                "tests_skipped": 0,
            }
            for kind in PersistedNotificationWorkerQualification.REQUIRED
        },
    }
    report.update(changes or {})
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return encode(payload) + "." + encode(private_key.sign(payload))


def harness(*, key=KEY):
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    store = SimpleNamespace(retrieve=AsyncMock(return_value=key))
    session = MagicMock()
    session.flush = AsyncMock()
    kwargs = {
        "test_runner_public_key_pem": pem,
        "signing_key_store": store,
        "issuer": ISSUER,
        "run_id": RUN,
        "branch": BRANCH,
        "environment": "staging",
        "source_commit": COMMIT,
        "source_digest": SOURCE,
        "target_digest": TARGET,
    }
    return private_key, store, session, kwargs


@pytest.mark.asyncio
async def test_trusted_handoff_only_stages_pending_evidence():
    private, store, session, kwargs = harness()
    result = await stage_verified_notification_qualification(
        session, attestation_token=signed_result(private), **kwargs
    )
    assert result == PendingNotificationQualification(
        qualification_id=f"jenkins:{RUN}", run_id=RUN
    )
    store.retrieve.assert_awaited_once_with(run_id=RUN)
    row = session.add.call_args.args[0]
    assert row.id == f"jenkins:{RUN}"
    assert row.environment == "staging"
    assert row.approved is False and row.revoked is False
    assert row.issued_by == f"jenkins:{ISSUER}"
    assert len(row.proof_tokens) == 3
    session.flush.assert_awaited_once()
    session.commit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"branch": "main"},
    {"run_id": "jenkins-other-456"},
    {"source_commit": "d" * 40},
    {"target_digest": "d" * 64},
    {"finished_at": 1},
])
async def test_invalid_provenance_rejected_before_secret_or_database(changes):
    private, store, session, kwargs = harness()
    with pytest.raises(CertificationAttestationError):
        await stage_verified_notification_qualification(
            session, attestation_token=signed_result(private, changes=changes),
            **kwargs,
        )
    store.retrieve.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_key_store_denial_prevents_database_write():
    private, store, session, kwargs = harness(key=None)
    with pytest.raises(PermissionError):
        await stage_verified_notification_qualification(
            session, attestation_token=signed_result(private), **kwargs
        )
    store.retrieve.assert_awaited_once_with(run_id=RUN)
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_database_duplicate_run_rejected_without_commit():
    private, _, session, kwargs = harness()
    session.flush.side_effect = IntegrityError(
        "duplicate qualification primary key", {}, RuntimeError("duplicate")
    )
    with pytest.raises(IntegrityError):
        await stage_verified_notification_qualification(
            session, attestation_token=signed_result(private), **kwargs
        )
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_tampered_attestation_fails_before_key_lookup():
    private, store, session, kwargs = harness()
    token = signed_result(private)
    encoded, signature = token.split(".")
    alternate = signed_result(private, changes={"branch": "main"}).split(".")[0]
    assert alternate != encoded
    with pytest.raises(CertificationAttestationError):
        await stage_verified_notification_qualification(
            session, attestation_token=alternate + "." + signature, **kwargs
        )
    store.retrieve.assert_not_awaited()
    session.add.assert_not_called()
