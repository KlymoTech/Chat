"""Broker health probes must be read-only and fail closed."""
from types import SimpleNamespace

import pytest

from northstar_api.modules.platform_runtime.broker_health import probe_rabbitmq, probe_sqs


class SqsClient:
    def __init__(self, payload=None, fail=False):
        self.payload = payload
        self.fail = fail
        self.calls = []

    def get_queue_attributes(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise OSError("simulated provider outage")
        return self.payload


@pytest.mark.asyncio
async def test_sqs_reports_health_from_metadata_only():
    client = SqsClient({"Attributes": {
        "ApproximateNumberOfMessages": "4",
        "ApproximateNumberOfMessagesNotVisible": "2",
    }})
    state = await probe_sqs(client, "https://sqs.us-east-1.amazonaws.com/123/jobs")
    assert state.status == "healthy"
    assert state.visible_messages == 4
    assert state.inflight_messages == 2
    assert len(client.calls) == 1
    assert client.calls[0]["AttributeNames"] == [
        "ApproximateNumberOfMessages",
        "ApproximateNumberOfMessagesNotVisible",
    ]


@pytest.mark.asyncio
async def test_sqs_failure_never_reports_healthy():
    result = await probe_sqs(
        SqsClient(fail=True), "https://sqs.us-east-1.amazonaws.com/123/jobs"
    )
    assert result.status == "unavailable"
    assert result.visible_messages is None


class RabbitChannel:
    def __init__(self, fail=False):
        self.fail = fail
        self.closed = False
        self.calls = []

    def queue_declare(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise OSError("missing queue")
        return SimpleNamespace(message_count=7, consumer_count=2)

    def close(self):
        self.closed = True


class RabbitConnection:
    def __init__(self, channel):
        self._channel = channel

    def channel(self):
        return self._channel


@pytest.mark.asyncio
async def test_rabbit_passive_probe_does_not_create_queue():
    channel = RabbitChannel()
    state = await probe_rabbitmq(RabbitConnection(channel), queue_name="durable.jobs")
    assert state.status == "healthy"
    assert state.visible_messages == 7
    assert channel.calls == [{"queue": "durable.jobs", "passive": True}]
    assert channel.closed


@pytest.mark.asyncio
async def test_rabbit_provider_failure_stays_unavailable_and_closes_channel():
    channel = RabbitChannel(fail=True)
    state = await probe_rabbitmq(RabbitConnection(channel), queue_name="durable.jobs")
    assert state.status == "unavailable"
    assert channel.closed


def test_invalid_probe_configuration_is_rejected():
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(probe_sqs(SqsClient(), "http://invalid"))
    with pytest.raises(ValueError):
        asyncio.run(probe_rabbitmq(RabbitConnection(RabbitChannel()), queue_name=""))
