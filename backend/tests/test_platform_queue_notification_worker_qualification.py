"""Worker startup qualification cannot be authorized by a label alone."""
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from northstar_api.modules.platform_runtime.queue_notification_worker_qualification import (
    NotificationQualificationRecord, PersistedNotificationWorkerQualification,
)

KEY = b"q" * 32
DIGEST = "a" * 64
TARGET = "b" * 64


def token(kind, *, expiry=3600, environment="qualification"):
    now = int(datetime.now(UTC).timestamp())
    payload = json.dumps({
        "kind": kind, "environment": environment,
        "source_digest": DIGEST, "target_digest": TARGET,
        "run_id": "pipeline-run-123", "issued_at": now - 10,
        "expires_at": now + expiry,
    }, separators=(",", ":")).encode()
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return encode(payload) + "." + encode(hmac.new(KEY, payload, hashlib.sha256).digest())


def make(record):
    store = SimpleNamespace(read=AsyncMock(return_value=record))
    verifier = PersistedNotificationWorkerQualification(
        store=store, qualification_id="evidence-123",
        environment="qualification", source_digest=DIGEST,
        target_digest=TARGET, signing_key=KEY,
    )
    return verifier, store


def record(*, approved=True, revoked=False, tokens=None):
    return NotificationQualificationRecord(
        "evidence-123", "qualification", DIGEST, TARGET,
        tokens if tokens is not None else tuple(token(k) for k in PersistedNotificationWorkerQualification.REQUIRED),
        approved, revoked,
    )


@pytest.mark.asyncio
async def test_signed_approved_evidence_permits_worker_start():
    verifier, store = make(record())
    assert await verifier.verify() is True
    store.read.assert_awaited_once_with("evidence-123")


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [
    None, record(approved=False), record(revoked=True),
    record(tokens=("unsigned", "unsigned", "unsigned")),
    record(tokens=(token("notification_worker"),)),
    record(tokens=tuple(token(k, expiry=-1) for k in PersistedNotificationWorkerQualification.REQUIRED)),
])
async def test_missing_revoked_unverified_or_expired_evidence_denied(value):
    verifier, _ = make(value)
    assert await verifier.verify() is False


@pytest.mark.asyncio
async def test_different_id_and_environment_denied():
    verifier, _ = make(NotificationQualificationRecord(
        "different-id", "qualification", DIGEST, TARGET, record().proof_tokens, True,
    ))
    assert not await verifier.verify()
    verifier, _ = make(NotificationQualificationRecord(
        "evidence-123", "production", DIGEST, TARGET, record().proof_tokens, True,
    ))
    assert not await verifier.verify()


@pytest.mark.asyncio
async def test_store_failure_fails_closed():
    verifier, store = make(record())
    store.read.side_effect = RuntimeError("private storage error")
    assert await verifier.verify() is False
