"""AWS Secrets Manager adapter: allowlist, rotation stage and failure isolation."""
from unittest.mock import MagicMock

import pytest

from northstar_api.modules.platform_runtime.aws_notification_secret_store import AwsNotificationSecretStore

ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:northstar/alerts"


def store(client):
    return AwsNotificationSecretStore(
        region="us-east-1", approved_secret_ids=frozenset({ARN}), client=client,
    )


@pytest.mark.asyncio
async def test_only_allowlisted_secret_can_be_fetched():
    client = MagicMock()
    client.get_secret_value.return_value = {
        "SecretBinary": b"x" * 32, "VersionStages": ["AWSCURRENT"],
    }
    service = store(client)
    assert await service.retrieve(ARN) == b"x" * 32
    client.get_secret_value.assert_called_once_with(SecretId=ARN, VersionStage="AWSCURRENT")
    assert await service.retrieve("arn:aws:secretsmanager:us-east-1:123456789012:secret:other") is None
    assert client.get_secret_value.call_count == 1


@pytest.mark.asyncio
async def test_rotation_stage_mismatch_returns_no_secret():
    client = MagicMock()
    client.get_secret_value.return_value = {
        "SecretString": "x" * 32, "VersionStages": ["AWSPREVIOUS"],
    }
    assert await store(client).retrieve(ARN) is None


@pytest.mark.asyncio
async def test_provider_failure_does_not_leak_credentials():
    client = MagicMock()
    client.get_secret_value.side_effect = PermissionError("secret-password")
    result = await store(client).retrieve(ARN)
    assert result is None


@pytest.mark.asyncio
async def test_missing_or_short_secret_is_rejected():
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": "short"}
    assert await store(client).retrieve(ARN) is None


def test_invalid_secret_allowlist_and_region_rejected():
    with pytest.raises(ValueError):
        AwsNotificationSecretStore(region="us-east-1", approved_secret_ids=frozenset({"plain-name"}), client=MagicMock())
    with pytest.raises(ValueError):
        AwsNotificationSecretStore(region="eu-west-1", approved_secret_ids=frozenset({ARN}), client=MagicMock())
