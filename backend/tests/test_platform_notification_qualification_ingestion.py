"""Only trusted certification pipelines can ingest valid, pending worker proofs."""
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.platform_runtime.queue_notification_qualification_ingestion import (
    QualificationIngestionRejected,
    ingest_notification_qualification,
)
from northstar_api.modules.platform_runtime.queue_notification_worker_qualification import (
    NotificationQualificationRecord, PersistedNotificationWorkerQualification,
)

KEY = b"q" * 32
SOURCE = "a" * 64
TARGET = "b" * 64


def token(kind: str) -> str:
    now = int(datetime.now(UTC).timestamp())
    data = json.dumps({
        "kind": kind, "environment": "staging", "source_digest": SOURCE,
        "target_digest": TARGET, "run_id": "pipeline-run-123",
        "issued_at": now - 10, "expires_at": now + 3600,
    }, separators=(",", ":")).encode()
    encoded = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return encoded(data) + "." + encoded(hmac.new(KEY, data, hashlib.sha256).digest())


def evidence(*, approved=False, tokens=None):
    return NotificationQualificationRecord(
        id="run-evidence-123", environment="staging",
        source_digest=SOURCE, target_digest=TARGET,
        proof_tokens=tokens if tokens is not None else tuple(
            token(k) for k in PersistedNotificationWorkerQualification.REQUIRED
        ),
        approved=approved,
    )


@pytest.mark.asyncio
async def test_valid_certification_is_pending_and_uncommitted():
    session = MagicMock()
    session.flush = AsyncMock()
    await ingest_notification_qualification(
        session, evidence=evidence(), trusted_pipeline=True, signing_key=KEY,
    )
    row = session.add.call_args.args[0]
    assert row.id == "run-evidence-123"
    assert row.approved is False and row.revoked is False
    session.flush.assert_awaited_once()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_untrusted_pipeline_cannot_write():
    session = MagicMock()
    with pytest.raises(PermissionError):
        await ingest_notification_qualification(
            session, evidence=evidence(), trusted_pipeline=False, signing_key=KEY,
        )
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_or_user_approved_proofs_cannot_write():
    for bad in (
        evidence(approved=True),
        evidence(tokens=("unsigned", "unsigned", "unsigned")),
        evidence(tokens=(token("notification_worker"),)),
    ):
        session = MagicMock()
        with pytest.raises(QualificationIngestionRejected):
            await ingest_notification_qualification(
                session, evidence=bad, trusted_pipeline=True, signing_key=KEY,
            )
        session.add.assert_not_called()


@pytest.mark.asyncio
async def test_missing_signing_key_blocks_ingestion():
    session = MagicMock()
    with pytest.raises(QualificationIngestionRejected):
        await ingest_notification_qualification(
            session, evidence=evidence(), trusted_pipeline=True, signing_key=b"",
        )
    session.add.assert_not_called()
