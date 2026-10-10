"""Opt-in notification runtime composition and startup guards."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.platform_runtime.queue_notification_runtime import (
    NotificationRuntime, NotificationRuntimeConfiguration,
)


def runtime(config, *, qualified=True):
    qualification = SimpleNamespace(verify=AsyncMock(return_value=qualified))
    routes = SimpleNamespace(get_route=AsyncMock(return_value=None))
    transports = SimpleNamespace(create=AsyncMock(return_value=None))
    item = NotificationRuntime(
        sessions=MagicMock(), routes=routes, transports=transports,
        qualification=qualification, configuration=config,
    )
    return item, qualification, routes, transports


@pytest.mark.asyncio
async def test_disabled_runtime_does_not_validate_or_dispatch():
    item, qualification, routes, transports = runtime(
        NotificationRuntimeConfiguration()
    )
    await item.run()
    qualification.verify.assert_not_awaited()
    routes.get_route.assert_not_awaited()
    transports.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unqualified_runtime_rejects_before_dispatch():
    item, qualification, routes, _ = runtime(
        NotificationRuntimeConfiguration(enabled=True, qualification_id="qa-record-1"),
        qualified=False,
    )
    with pytest.raises(PermissionError, match="qualification"):
        await item.run()
    qualification.verify.assert_awaited_once()
    routes.get_route.assert_not_awaited()


@pytest.mark.asyncio
async def test_qualified_worker_stops_cleanly_without_provider_calls():
    item, qualification, routes, _ = runtime(
        NotificationRuntimeConfiguration(
            enabled=True, qualification_id="qa-record-1",
            poll_seconds=0.1, max_batch=2,
        ),
    )
    # No claims should occur once shutdown is requested.
    item.request_stop()
    await asyncio.wait_for(item.run(), timeout=1)
    qualification.verify.assert_awaited_once()
    routes.get_route.assert_not_awaited()


def test_enablement_requires_explicit_evidence():
    with pytest.raises(ValueError, match="qualification"):
        NotificationRuntimeConfiguration(enabled=True)
    with pytest.raises(ValueError, match="qualification"):
        NotificationRuntimeConfiguration(enabled=True, qualification_id="   ")


@pytest.mark.parametrize("kwargs", [
    {"max_attempts": 0}, {"lease_seconds": 1}, {"max_batch": 101},
    {"poll_seconds": 0},
])
def test_runtime_rejects_unbounded_or_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        NotificationRuntimeConfiguration(**kwargs)
