from unittest.mock import AsyncMock, Mock

import pytest

from northstar_api.services import platform_activity


@pytest.mark.asyncio
async def test_activity_signal_is_opt_in_and_uses_workload_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLATFORM_ACTIVITY_TABLE", raising=False)
    monkeypatch.delenv("PLATFORM_ACTIVITY_KEY", raising=False)
    client = Mock()
    monkeypatch.setattr(platform_activity.boto3, "client", client)
    assert await platform_activity.mark_platform_activity() is False
    client.assert_not_called()

    monkeypatch.setenv("PLATFORM_ACTIVITY_TABLE", "activity")
    monkeypatch.setenv("PLATFORM_ACTIVITY_KEY", "northstar:dev")
    marker = Mock()
    marker.mark_activity = AsyncMock()
    monkeypatch.setattr(platform_activity, "DynamoDbActivityMarker", Mock(return_value=marker))
    assert await platform_activity.mark_platform_activity() is True
    client.assert_called_once_with("dynamodb")
    marker.mark_activity.assert_awaited_once()


@pytest.mark.asyncio
async def test_marker_failure_does_not_fail_completed_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_ACTIVITY_TABLE", "activity")
    monkeypatch.setenv("PLATFORM_ACTIVITY_KEY", "northstar:dev")
    monkeypatch.setattr(platform_activity.boto3, "client", Mock(side_effect=RuntimeError("unavailable")))
    assert await platform_activity.mark_platform_activity() is False
