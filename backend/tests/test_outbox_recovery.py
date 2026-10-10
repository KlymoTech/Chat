from unittest.mock import AsyncMock, Mock

import pytest

from northstar_api.handlers import outbox_recovery


@pytest.mark.asyncio
async def test_recovery_skips_database_when_activity_is_old(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_ACTIVITY_TABLE", "activity")
    monkeypatch.setenv("PLATFORM_ACTIVITY_KEY", "northstar:test")
    monkeypatch.setattr(outbox_recovery.boto3, "client", Mock())
    gate = AsyncMock(return_value=(False, None))
    relay = AsyncMock()
    monkeypatch.setattr(outbox_recovery, "run_if_recently_active", gate)
    monkeypatch.setattr(outbox_recovery, "run_once", relay)

    assert await outbox_recovery.run() == {"status": "skipped", "published": 0}
    relay.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_recovery_batch_schedules_continuation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_ACTIVITY_TABLE", "activity")
    monkeypatch.setenv("PLATFORM_ACTIVITY_KEY", "northstar:test")
    monkeypatch.setattr(outbox_recovery.boto3, "client", Mock())
    monkeypatch.setattr(
        outbox_recovery,
        "run_if_recently_active",
        AsyncMock(return_value=(True, outbox_recovery.BATCH_SIZE)),
    )
    nudge = Mock(return_value=True)
    monkeypatch.setattr(outbox_recovery, "send_outbox_nudge", nudge)

    assert await outbox_recovery.run() == {
        "status": "ran",
        "published": outbox_recovery.BATCH_SIZE,
    }
    nudge.assert_called_once()
