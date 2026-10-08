"""RabbitMQ broker-health API is configured server-side and fails closed."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.super_admin.api.runtime import read_platform_rabbitmq_health


@pytest.mark.asyncio
async def test_rabbitmq_unconfigured_does_not_connect(monkeypatch):
    import kombu

    monkeypatch.delenv("PLATFORM_QUEUE_HEALTH_RABBITMQ_QUEUE", raising=False)
    create = MagicMock()
    monkeypatch.setattr(kombu, "Connection", create)
    result = await read_platform_rabbitmq_health(None)
    assert result["status"] == "unconfigured"
    assert result["scope"] == "shared_queue"
    create.assert_not_called()


@pytest.mark.asyncio
async def test_rabbitmq_probe_uses_configured_queue_and_closes_connection(monkeypatch):
    import kombu
    from northstar_api.modules.platform_runtime import broker_health

    monkeypatch.setenv("PLATFORM_QUEUE_HEALTH_RABBITMQ_QUEUE", "durable.jobs")
    connection = MagicMock()
    create = MagicMock(return_value=connection)
    monkeypatch.setattr(kombu, "Connection", create)
    probe = AsyncMock(return_value=SimpleNamespace(as_json=lambda: {
        "provider": "rabbitmq", "status": "healthy", "detail": "passive_queue_read_ok",
        "visible_messages": 4, "inflight_messages": None,
    }))
    monkeypatch.setattr(broker_health, "probe_rabbitmq", probe)
    result = await read_platform_rabbitmq_health(None)
    assert result["status"] == "healthy"
    assert result["scope"] == "shared_queue"
    assert probe.await_args.kwargs["queue_name"] == "durable.jobs"
    connection.connect.assert_called_once()
    connection.release.assert_called_once()


@pytest.mark.asyncio
async def test_connection_failure_does_not_leak_secret(monkeypatch):
    import kombu

    monkeypatch.setenv("PLATFORM_QUEUE_HEALTH_RABBITMQ_QUEUE", "durable.jobs")
    connection = MagicMock()
    connection.connect.side_effect = OSError("password=secret")
    monkeypatch.setattr(kombu, "Connection", MagicMock(return_value=connection))
    result = await read_platform_rabbitmq_health(None)
    assert result["status"] == "unavailable"
    assert "secret" not in str(result)
    connection.release.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_queue_name_is_rejected(monkeypatch):
    monkeypatch.setenv("PLATFORM_QUEUE_HEALTH_RABBITMQ_QUEUE", "invalid queue")
    result = await read_platform_rabbitmq_health(None)
    assert result["status"] == "unavailable"
    assert result["detail"] == "invalid_probe_configuration"
