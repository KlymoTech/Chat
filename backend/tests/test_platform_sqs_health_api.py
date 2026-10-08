"""SQS health API never trusts user-supplied queue URLs or exposes credentials."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from northstar_api.modules.super_admin.api.runtime import read_platform_sqs_health


@pytest.mark.asyncio
async def test_unconfigured_probe_never_creates_aws_client(monkeypatch):
    monkeypatch.delenv("PLATFORM_QUEUE_HEALTH_SQS_URL", raising=False)
    result = await read_platform_sqs_health(None)
    assert result["status"] == "unconfigured"
    assert result["scope"] == "shared_queue"


@pytest.mark.asyncio
async def test_configured_probe_uses_server_url_only(monkeypatch):
    import boto3

    url = "https://sqs.us-east-1.amazonaws.com/123/jobs"
    monkeypatch.setenv("PLATFORM_QUEUE_HEALTH_SQS_URL", url)
    client = object()
    created = MagicMock(return_value=client)
    monkeypatch.setattr(boto3, "client", created)
    from northstar_api.modules.platform_runtime import broker_health

    result = SimpleNamespace(as_json=lambda: {
        "provider": "sqs", "status": "healthy", "detail": "metadata_read_ok",
        "visible_messages": 1, "inflight_messages": 0,
    })
    probe = AsyncMock(return_value=result)
    monkeypatch.setattr(broker_health, "probe_sqs", probe)
    response = await read_platform_sqs_health(None)
    assert response["scope"] == "shared_queue"
    assert response["status"] == "healthy"
    assert probe.await_args.args == (client, url)
    created.assert_called_once()


@pytest.mark.asyncio
async def test_client_creation_error_fails_closed(monkeypatch):
    import boto3

    monkeypatch.setenv("PLATFORM_QUEUE_HEALTH_SQS_URL", "https://sqs.us-east-1.amazonaws.com/123/jobs")
    monkeypatch.setattr(boto3, "client", MagicMock(side_effect=RuntimeError("secret")))
    result = await read_platform_sqs_health(None)
    assert result["status"] == "unavailable"
    assert "secret" not in str(result)
