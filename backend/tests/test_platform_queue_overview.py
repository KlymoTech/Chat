"""Queue overview preserves tenant isolation and broker uncertainty."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from northstar_api.modules.super_admin.api import runtime


@pytest.mark.asyncio
async def test_overview_preserves_shared_scope_and_degraded_durable_state(monkeypatch):
    tenant = uuid4()
    principal = SimpleNamespace(tenant_id=tenant)
    durable = {"status": "degraded", "tenant_id": str(tenant), "dead_letter": 2}
    monkeypatch.setattr(runtime, "read_platform_queue_health", AsyncMock(return_value=durable))
    monkeypatch.setattr(runtime, "read_platform_sqs_health", AsyncMock(return_value={
        "provider": "sqs", "status": "healthy", "scope": "shared_queue",
    }))
    monkeypatch.setattr(runtime, "read_platform_rabbitmq_health", AsyncMock(return_value={
        "provider": "rabbitmq", "status": "unconfigured", "scope": "shared_queue",
    }))
    output = await runtime.read_platform_queue_overview(principal, MagicMock())
    assert output["status"] == "degraded"
    assert output["tenant_id"] == str(tenant)
    assert output["durable_jobs"] == durable
    assert output["broker_scope"] == "shared_queue"
    assert not output["qualified"]


@pytest.mark.asyncio
async def test_overview_does_not_infer_health_for_unconfigured_provider(monkeypatch):
    monkeypatch.setattr(runtime, "read_platform_queue_health", AsyncMock(return_value={"status": "operational"}))
    monkeypatch.setattr(runtime, "read_platform_sqs_health", AsyncMock(return_value={
        "provider": "sqs", "status": "healthy", "scope": "shared_queue",
    }))
    monkeypatch.setattr(runtime, "read_platform_rabbitmq_health", AsyncMock(return_value={
        "provider": "rabbitmq", "status": "unconfigured", "scope": "shared_queue",
    }))
    result = await runtime.read_platform_queue_overview(SimpleNamespace(tenant_id=uuid4()), MagicMock())
    assert result["status"] == "unknown"


@pytest.mark.asyncio
async def test_broker_error_is_redacted_and_degraded(monkeypatch):
    monkeypatch.setattr(runtime, "read_platform_queue_health", AsyncMock(return_value={"status": "operational"}))
    monkeypatch.setattr(runtime, "read_platform_sqs_health", AsyncMock(side_effect=RuntimeError("secret=123")))
    monkeypatch.setattr(runtime, "read_platform_rabbitmq_health", AsyncMock(return_value={
        "provider": "rabbitmq", "status": "healthy", "scope": "shared_queue",
    }))
    result = await runtime.read_platform_queue_overview(SimpleNamespace(tenant_id=uuid4()), MagicMock())
    assert result["status"] == "degraded"
    assert result["brokers"]["sqs"]["status"] == "unavailable"
    assert "secret" not in str(result)


@pytest.mark.asyncio
async def test_missing_tenant_is_rejected_before_probes(monkeypatch):
    probe = AsyncMock()
    monkeypatch.setattr(runtime, "read_platform_sqs_health", probe)
    with pytest.raises(HTTPException) as error:
        await runtime.read_platform_queue_overview(SimpleNamespace(tenant_id=None), MagicMock())
    assert error.value.status_code == 403
    probe.assert_not_awaited()
