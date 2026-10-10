from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from northstar_api.services.retention_preview import (
    has_local_retention_hold,
    preview_conversation_retention,
    retention_cutoff,
)


@pytest.mark.parametrize(
    "policy",
    [
        None,
        {},
        {"retentionDays": "90"},
        {"retentionDays": True},
        {"retentionDays": 0},
        {"retentionDays": 3651},
    ],
)
def test_policy_missing_or_invalid_cannot_generate_expiration(policy: object) -> None:
    assert retention_cutoff(policy, as_of=datetime.now(UTC)) is None


def test_timezone_aware_policy_cutoff_is_in_utc() -> None:
    moment = datetime(2026, 10, 11, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    cutoff = retention_cutoff({"retentionDays": 90}, as_of=moment)
    assert cutoff == moment.astimezone(UTC) - timedelta(days=90)
    with pytest.raises(ValueError, match="timezone-aware"):
        retention_cutoff({"retentionDays": 90}, as_of=moment.replace(tzinfo=None))


@pytest.mark.parametrize("name", ["legalHold", "retentionHold", "privacyHold"])
def test_explicit_agent_hold_blocks_candidates(name: str) -> None:
    assert has_local_retention_hold({name: True})
    assert not has_local_retention_hold({name: False})
    assert has_local_retention_hold({name: "true"})


@pytest.mark.asyncio
async def test_scoped_read_only_preview_uses_latest_message_activity() -> None:
    tid, wid = uuid4(), uuid4()
    older = datetime(2025, 10, 11, tzinfo=UTC)
    recent = datetime(2026, 10, 10, tzinfo=UTC)
    cid1, cid2, cid3 = uuid4(), uuid4(), uuid4()
    result = MagicMock()
    result.all.return_value = [
        (cid1, older, older, None, {"retentionDays": 90}),
        (cid2, older, older, recent, {"retentionDays": 90}),
        (cid3, older, older, None, {"retentionDays": 90, "legalHold": True}),
    ]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    summary = await preview_conversation_retention(
        db, tenant_id=tid, workspace_id=wid,
        as_of=datetime(2026, 10, 11, tzinfo=UTC), max_rows=20,
    )
    assert summary.candidate_ids == (cid1,)
    assert summary.recent == 1
    assert summary.held == 1
    assert summary.invalid_policy == 0
    assert summary.requires_external_legal_hold_review
    stmt = db.execute.await_args.args[0]
    query = str(stmt.compile(dialect=postgresql.dialect()))
    assert "conversations.tenant_id" in query
    assert "conversations.workspace_id" in query
    assert "messages.tenant_id" in query
    assert "messages.workspace_id" in query
    assert "LIMIT" in query.upper()
    assert "DELETE" not in query.upper()
    assert "UPDATE " not in query.upper()


@pytest.mark.asyncio
async def test_preview_enforces_bounded_batches_and_reports_truncation() -> None:
    tid, wid = uuid4(), uuid4()
    older = datetime(2025, 1, 1, tzinfo=UTC)
    rows = [(uuid4(), older, older, None, {"retentionDays": 90}) for _ in range(3)]
    result = MagicMock()
    result.all.return_value = rows
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    report = await preview_conversation_retention(
        db, tenant_id=tid, workspace_id=wid,
        as_of=datetime(2026, 10, 11, tzinfo=UTC), max_rows=2,
    )
    assert report.inspected == 2
    assert report.truncated is True
    assert len(report.candidate_ids) == 2
    with pytest.raises(ValueError, match="1..1000"):
        await preview_conversation_retention(
            db, tenant_id=tid, workspace_id=wid,
            as_of=datetime.now(UTC), max_rows=0,
        )


@pytest.mark.asyncio
async def test_naive_database_timestamps_are_not_candidates() -> None:
    cid = uuid4()
    older = datetime(2025, 1, 1)
    result = MagicMock()
    result.all.return_value = [(cid, older, older, None, {"retentionDays": 90})]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    report = await preview_conversation_retention(
        db, tenant_id=uuid4(), workspace_id=uuid4(),
        as_of=datetime.now(UTC), max_rows=1,
    )
    assert report.candidate_ids == ()
    assert report.invalid_policy == 1


@pytest.mark.asyncio
async def test_preview_never_executes_when_parameters_invalid() -> None:
    db = MagicMock()
    db.execute = AsyncMock()
    with pytest.raises(ValueError):
        await preview_conversation_retention(
            db, tenant_id="wrong", workspace_id=uuid4(),
            as_of=datetime.now(UTC),
        )
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unverifiable_latest_message_timestamp_cannot_be_candidate() -> None:
    cid = uuid4()
    older = datetime(2025, 1, 1, tzinfo=UTC)
    message_without_timezone = datetime(2026, 10, 10)
    result = MagicMock()
    result.all.return_value = [
        (cid, older, older, message_without_timezone, {"retentionDays": 90})
    ]
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    report = await preview_conversation_retention(
        db, tenant_id=uuid4(), workspace_id=uuid4(),
        as_of=datetime.now(UTC), max_rows=1,
    )
    assert report.candidate_ids == ()
    assert report.invalid_policy == 1
