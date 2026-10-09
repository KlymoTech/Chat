"""Opt-in worker lifecycle never sends while disabled and drains on stop."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.platform_runtime.queue_notification_worker import (
    NotificationWorker, NotificationWorkerSettings,
)


@pytest.mark.asyncio
async def test_default_disabled_never_calls_dispatcher():
    dispatch = MagicMock(dispatch_one=AsyncMock(return_value=True))
    worker = NotificationWorker(dispatch)
    assert await worker.run_once() == 0
    await worker.run()
    dispatch.dispatch_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_is_strictly_bounded():
    dispatch = MagicMock(dispatch_one=AsyncMock(return_value=True))
    worker = NotificationWorker(
        dispatch, settings=NotificationWorkerSettings(enabled=True, max_batch=3)
    )
    assert await worker.run_once() == 3
    assert dispatch.dispatch_one.await_count == 3


@pytest.mark.asyncio
async def test_empty_queue_stops_batch_immediately():
    dispatch = MagicMock(dispatch_one=AsyncMock(return_value=False))
    worker = NotificationWorker(
        dispatch, settings=NotificationWorkerSettings(enabled=True, max_batch=20)
    )
    assert await worker.run_once() == 0
    dispatch.dispatch_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_drains_without_starting_another_delivery():
    started = asyncio.Event()
    release = asyncio.Event()

    async def deliver():
        started.set()
        await release.wait()
        return True

    dispatch = MagicMock(dispatch_one=AsyncMock(side_effect=deliver))
    worker = NotificationWorker(
        dispatch, settings=NotificationWorkerSettings(
            enabled=True, max_batch=5, poll_seconds=0.1
        ),
    )
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), 1)
    worker.request_stop()
    release.set()
    await asyncio.wait_for(task, 1)
    assert dispatch.dispatch_one.await_count == 1


@pytest.mark.parametrize("kwargs", [
    {"max_batch": 0}, {"max_batch": 101},
    {"poll_seconds": 0}, {"poll_seconds": 100},
])
def test_invalid_worker_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        NotificationWorkerSettings(**kwargs)
