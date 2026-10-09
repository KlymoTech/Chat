"""Externally signed worker proofs are admitted only as unapproved records."""
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.platform_runtime.queue_notification_qualification_admission import (
    admit_notification_qualification,
)
from northstar_api.modules.platform_runtime.queue_notification_worker_qualification import (
    PersistedNotificationWorkerQualification,
)

KEY = b"verification-only-key-for-certification" * 2
SOURCE = "a" * 64
TARGET = "b" * 64


def token(kind, *, environment="qa"):
    instant = int(datetime.now(UTC).timestamp())
    body = json.dumps({
        "kind": kind, "environment": environment,
        "source_digest": SOURCE, "target_digest": TARGET,
        "run_id": "jenkins-build-1234", "issued_at": instant - 10,
        "expires_at": instant + 3600,
    }, separators=(",", ":")).encode()
    enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    return enc(body) + "." + enc(hmac.new(KEY, body, hashlib.sha256).digest())


def proofs():
    return tuple(token(kind) for kind in PersistedNotificationWorkerQualification.REQUIRED)


def kwargs():
    return dict(
        qualification_id="jenkins-build-1234", environment="qa",
        source_digest=SOURCE, target_digest=TARGET,
        proof_tokens=proofs(), signing_key=KEY,
        pipeline_authorized=True,
    )


@pytest.mark.asyncio
async def test_verified_evidence_is_stored_unapproved():
    session = MagicMock()
    session.flush = AsyncMock()
    await admit_notification_qualification(session, **kwargs())
    item = session.add.call_args.args[0]
    assert item.approved is False
    assert item.revoked is False
    assert item.id == "jenkins-build-1234"
    assert len(item.proof_tokens) == 3
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_unprivileged_admission_never_mutates_database():
    session = MagicMock()
    options = kwargs()
    options["pipeline_authorized"] = False
    with pytest.raises(PermissionError):
        await admit_notification_qualification(session, **options)
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_signature_and_wrong_environment_fail_closed():
    session = MagicMock()
    options = kwargs()
    options["proof_tokens"] = tuple(t[:-1] + "x" for t in proofs())
    with pytest.raises(ValueError):
        await admit_notification_qualification(session, **options)
    options = kwargs()
    options["environment"] = "production"
    with pytest.raises(ValueError):
        await admit_notification_qualification(session, **options)
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_flush_error_is_not_masked_or_committed():
    session = MagicMock()
    session.flush = AsyncMock(side_effect=RuntimeError("unique constraint"))
    with pytest.raises(RuntimeError):
        await admit_notification_qualification(session, **kwargs())
    assert not hasattr(session, "commit_called")
