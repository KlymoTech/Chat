from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from northstar_api.workers import crm_reconciliation


@pytest.mark.asyncio
async def test_scheduled_reconciliation_does_not_open_database_when_inactive() -> None:
    now = datetime.now(UTC)
    marker = Mock()
    marker.last_activity = AsyncMock(return_value=now - timedelta(hours=3))
    factory = Mock()

    result = await crm_reconciliation.run_scheduled_once(
        marker, factory, activity_key="northstar:dev", now=now,
    )

    assert result is None
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_reconciliation_runs_after_recent_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    marker = Mock()
    marker.last_activity = AsyncMock(return_value=now - timedelta(minutes=5))
    session = Mock()
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = Mock(return_value=context)
    run_once = AsyncMock(return_value={"recovered": 1, "verified": 0, "deferred": 0})
    monkeypatch.setattr(crm_reconciliation, "run_once", run_once)

    result = await crm_reconciliation.run_scheduled_once(
        marker, factory, activity_key="northstar:dev", now=now,
    )

    assert result == {"recovered": 1, "verified": 0, "deferred": 0}
    factory.assert_called_once()
    run_once.assert_awaited_once_with(session)
