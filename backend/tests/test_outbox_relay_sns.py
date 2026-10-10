import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from northstar_api.handlers import outbox_relay


@pytest.mark.asyncio
async def test_sns_fifo_publisher_uses_stable_event_deduplication_and_tenant_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    monkeypatch.setattr(outbox_relay.boto3, "client", Mock(return_value=client))
    producer = outbox_relay.SnsFifoProducer(
        "arn:aws:sns:ap-south-1:123456789012:northstar-events.fifo"
    )
    envelope = {
        "eventId": "a07cd18a-828a-4afe-b4df-7c5629604629",
        "tenantId": "f3471934-0782-4982-b39e-82629104c55a",
        "eventType": "conversation.created.v1",
        "payload": {"safe": True},
    }

    await producer.send_and_wait("conversation.created.v1", envelope, key="aggregate-1")
    kwargs = client.publish.call_args.kwargs
    assert kwargs["TopicArn"].endswith(".fifo")
    assert kwargs["MessageGroupId"] == f"{envelope['tenantId']}:aggregate-1"
    assert kwargs["MessageDeduplicationId"] == envelope["eventId"]
    assert kwargs["MessageAttributes"]["eventType"]["StringValue"] == envelope["eventType"]
    assert json.loads(kwargs["Message"]) == envelope


def test_sns_backend_never_requires_kafka(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLATFORM_EVENTS_BACKEND", "sns")
    monkeypatch.setenv(
        "PLATFORM_DOMAIN_EVENTS_TOPIC_ARN",
        "arn:aws:sns:ap-south-1:123456789012:northstar-events.fifo",
    )
    client = Mock()
    monkeypatch.setattr(outbox_relay.boto3, "client", Mock(return_value=client))
    producer = outbox_relay.make_producer(SimpleNamespace(kafka_enabled=False))
    assert isinstance(producer, outbox_relay.SnsFifoProducer)


def test_invalid_backend_or_non_fifo_topic_fails_before_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLATFORM_EVENTS_BACKEND", "unknown")
    with pytest.raises(ValueError, match="kafka or sns"):
        outbox_relay.make_producer(SimpleNamespace(kafka_enabled=False))

    monkeypatch.setenv("PLATFORM_EVENTS_BACKEND", "sns")
    monkeypatch.setenv(
        "PLATFORM_DOMAIN_EVENTS_TOPIC_ARN",
        "arn:aws:sns:ap-south-1:123456789012:not-fifo",
    )
    with pytest.raises(ValueError, match="SNS FIFO"):
        outbox_relay.make_producer(SimpleNamespace(kafka_enabled=False))
