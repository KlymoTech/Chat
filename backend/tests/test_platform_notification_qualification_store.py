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


@pytest.mark.asyncio
async def test_unlinked_jenkins_evidence_not_returned_to_worker():
    row = SimpleNamespace(
        id="jenkins:jenkins-build-123", environment="staging",
        source_digest="a" * 64, target_digest="b" * 64,
        proof_tokens=["token1", "token2", "token3"],
        approved=True, revoked=False,
    )
    factory, session = sessions(row)
    session.get.side_effect = [row, None]
    assert await PostgresNotificationQualificationStore(factory).read(row.id) is None
    assert session.get.await_count == 2


@pytest.mark.asyncio
async def test_linked_jenkins_evidence_can_be_read_for_proof_verification():
    row = SimpleNamespace(
        id="jenkins:jenkins-build-123", environment="staging",
        source_digest="a" * 64, target_digest="b" * 64,
        proof_tokens=["token1", "token2", "token3"],
        approved=True, revoked=False,
    )
    link = SimpleNamespace(
        environment="staging", source_digest="a" * 64,
        target_digest="b" * 64, run_id="jenkins-build-123",
    )
    factory, session = sessions(row)
    session.get.side_effect = [row, link]
    found = await PostgresNotificationQualificationStore(factory).read(row.id)
    assert found is not None and found.approved is True
    assert found.proof_tokens == tuple(row.proof_tokens)


@pytest.mark.asyncio
async def test_stale_link_is_denied_even_for_approved_jenkins_evidence():
    row = SimpleNamespace(
        id="jenkins:jenkins-build-123", environment="staging",
        source_digest="a" * 64, target_digest="b" * 64,
        proof_tokens=["token1", "token2", "token3"],
        approved=True, revoked=False,
    )
    link = SimpleNamespace(
        environment="production", source_digest="a" * 64,
        target_digest="b" * 64, run_id="jenkins-build-123",
    )
    factory, session = sessions(row)
    session.get.side_effect = [row, link]
    assert await PostgresNotificationQualificationStore(factory).read(row.id) is None
