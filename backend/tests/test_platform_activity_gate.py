from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from northstar_api.modules.platform_runtime.activity_gate import run_if_recently_active
from northstar_api.modules.platform_runtime.dynamodb_activity_marker import DynamoDbActivityMarker


@pytest.mark.asyncio
async def test_scheduled_operation_only_wakes_database_after_recent_marker() -> None:
    now = datetime.now(UTC)
    marker = Mock()
    marker.last_activity = AsyncMock(return_value=now - timedelta(minutes=30))
    operation = AsyncMock(return_value=7)
    assert await run_if_recently_active(marker, "northstar:dev", operation, now=now) == (True, 7)
    operation.assert_awaited_once()

    marker.last_activity.return_value = now - timedelta(hours=3)
    operation.reset_mock()
    assert await run_if_recently_active(marker, "northstar:dev", operation, now=now) == (False, None)
    operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_marker_and_read_failure_never_run_operation() -> None:
    marker = Mock()
    marker.last_activity = AsyncMock(return_value=None)
    operation = AsyncMock()
    assert await run_if_recently_active(marker, "northstar:dev", operation, now=datetime.now(UTC)) == (False, None)
    marker.last_activity.side_effect = RuntimeError("marker unavailable")
    with pytest.raises(RuntimeError, match="marker unavailable"):
        await run_if_recently_active(marker, "northstar:dev", operation, now=datetime.now(UTC))
    operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_dynamodb_adapter_reads_and_marks_without_database_access() -> None:
    client = Mock()
    client.get_item.return_value = {"Item": {"last_activity_epoch": {"N": "1728000000"}}}
    marker = DynamoDbActivityMarker(client, "activity")
    assert await marker.last_activity("northstar:dev") == datetime.fromtimestamp(1728000000, UTC)
    await marker.mark_activity("northstar:dev", at=datetime.fromtimestamp(1728000001, UTC))
    assert client.get_item.call_args.kwargs["ConsistentRead"] is True
    assert "attribute_not_exists" in client.update_item.call_args.kwargs["ConditionExpression"]
