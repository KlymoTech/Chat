from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from northstar_api.handlers import crm_reconcile


@pytest.mark.asyncio
async def test_idle_crm_schedule_never_creates_database_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = Mock()
    marker.last_activity = AsyncMock(return_value=None)
    engine_builder = Mock()
    monkeypatch.setenv("PLATFORM_ACTIVITY_TABLE", "activity")
    monkeypatch.setenv("PLATFORM_ACTIVITY_KEY", "northstar:dev")
    monkeypatch.setattr(crm_reconcile.boto3, "client", Mock(return_value=Mock()))
    monkeypatch.setattr(crm_reconcile, "DynamoDbActivityMarker", Mock(return_value=marker))
    monkeypatch.setattr(crm_reconcile, "build_engine", engine_builder)

    assert await crm_reconcile.run() is None
    engine_builder.assert_not_called()


@pytest.mark.asyncio
async def test_active_crm_schedule_runs_and_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = Mock()
    marker.last_activity = AsyncMock(return_value=datetime.now(UTC) - timedelta(minutes=5))
    engine = Mock()
    engine.dispose = AsyncMock()
    session = Mock()
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = Mock(return_value=context)
    worker = AsyncMock(return_value={"recovered": 0, "verified": 1, "deferred": 0})
    engine_builder = Mock(return_value=engine)
    monkeypatch.setenv("PLATFORM_ACTIVITY_TABLE", "activity")
    monkeypatch.setenv("PLATFORM_ACTIVITY_KEY", "northstar:dev")
    monkeypatch.setattr(crm_reconcile.boto3, "client", Mock(return_value=Mock()))
    monkeypatch.setattr(crm_reconcile, "DynamoDbActivityMarker", Mock(return_value=marker))
    monkeypatch.setattr(crm_reconcile, "build_engine", engine_builder)
    monkeypatch.setattr(crm_reconcile, "async_sessionmaker", Mock(return_value=factory))
    monkeypatch.setattr(crm_reconcile, "run_once", worker)

    assert await crm_reconcile.run() == {"recovered": 0, "verified": 1, "deferred": 0}
    worker.assert_awaited_once_with(session)
    engine.dispose.assert_awaited_once()
    scoped_settings = engine_builder.call_args.args[0]
    assert scoped_settings.database_pool_size == 1
    assert scoped_settings.database_max_overflow == 0
