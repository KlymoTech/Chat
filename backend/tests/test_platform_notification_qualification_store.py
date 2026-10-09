"""Qualification evidence repository exposes only exact, well-formed records."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.platform_runtime.queue_notification_qualification_store import PostgresNotificationQualificationStore


def sessions(record):
    session = MagicMock()
    session.get = AsyncMock(return_value=record)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=session), session


@pytest.mark.asyncio
async def test_exact_id_read_preserves_revocation_and_approval():
    row = SimpleNamespace(
        id="qa-run-123", environment="production",
        source_digest="a" * 64, target_digest="b" * 64,
        proof_tokens=["signed.proof"], approved=True, revoked=True,
        created_at=datetime.now(UTC),
    )
    factory, session = sessions(row)
    record = await PostgresNotificationQualificationStore(factory).read("qa-run-123")
    assert record is not None
    assert record.revoked and record.approved
    assert record.proof_tokens == ("signed.proof",)
    session.get.assert_awaited_once()
    assert session.get.await_args.args[1] == "qa-run-123"


@pytest.mark.asyncio
async def test_missing_and_invalid_records_are_not_trusted():
    factory, _ = sessions(None)
    assert await PostgresNotificationQualificationStore(factory).read("missing") is None
    bad_factory, _ = sessions(SimpleNamespace(proof_tokens={"not": "a list"}))
    assert await PostgresNotificationQualificationStore(bad_factory).read("invalid") is None


@pytest.mark.asyncio
async def test_invalid_id_cannot_query_database():
    factory, session = sessions(None)
    store = PostgresNotificationQualificationStore(factory)
    assert await store.read("") is None
    assert await store.read("a" * 129) is None
    session.get.assert_not_awaited()
