"""Tenant isolation and read-only queue health contract tests."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.platform_runtime.queue_health import assess_queue_health
from northstar_api.modules.super_admin.api.runtime import read_platform_queue_health


@pytest.mark.asyncio
async def test_queue_health_reports_degraded_backlog_without_broker_claims():
    session = MagicMock()
    tenant = uuid4()
    now = datetime.now(UTC)
    results = MagicMock()
    results.all.return_value = [("queued", 3), ("dead_letter", 1)]
    session.execute = AsyncMock(return_value=results)
    session.scalar = AsyncMock(side_effect=[2, 1, now - timedelta(seconds=400)])
    health = await assess_queue_health(session, tenant_id=tenant, now=now)
    assert health.status == "degraded"
    assert health.overdue == 2
    assert health.stale_leases == 1
    assert health.oldest_pending_seconds == 400
    assert health.broker_health == "unknown"
    assert health.as_json()["tenant_id"] == str(tenant)
    for call in [session.execute.await_args, *session.scalar.await_args_list]:
        query = call.args[0]
        assert tenant in query.compile().params.values()


@pytest.mark.asyncio
async def test_empty_queue_reports_unknown_broker():
    session = MagicMock()
    results = MagicMock()
    results.all.return_value = []
    session.execute = AsyncMock(return_value=results)
    session.scalar = AsyncMock(side_effect=[0, 0, None])
    health = await assess_queue_health(session, tenant_id=uuid4())
    assert health.status == "empty"
    assert health.broker_health == "unknown"


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_missing_tenant():
    session = MagicMock()
    with pytest.raises(HTTPException) as failure:
        await read_platform_queue_health(SimpleNamespace(tenant_id=None), session)
    assert failure.value.status_code == 403
