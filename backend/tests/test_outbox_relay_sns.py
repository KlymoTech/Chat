import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from northstar_api.handlers import outbox_relay

TOPIC = "arn:aws:sns:ap-south-1:123456789012:northstar-events.fifo"
SUBSCRIPTION = f"{TOPIC}:a07cd18a-828a-4afe-b4df-7c5629604629"
QUEUE = "arn:aws:sqs:ap-south-1:123456789012:northstar-events.fifo"
DELIVERY_DLQ = "arn:aws:sqs:ap-south-1:123456789012:northstar-subscription-dlq.fifo"


def subscription_attributes() -> dict:
    from northstar_api.handlers.domain_events import ROUTED_TYPES

    return {"Attributes": {
        "SubscriptionArn": SUBSCRIPTION,
        "TopicArn": TOPIC,
        "Protocol": "sqs",
        "Endpoint": QUEUE,
        "FilterPolicyScope": "MessageAttributes",
        "RawMessageDelivery": "false",
        "FilterPolicy": json.dumps({"eventType": sorted(ROUTED_TYPES)}),
        "RedrivePolicy": json.dumps({"deadLetterTargetArn": DELIVERY_DLQ}),
    }}


@pytest.mark.asyncio
async def test_sns_fifo_publisher_uses_stable_event_deduplication_and_tenant_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    monkeypatch.setattr(outbox_relay.boto3, "client", Mock(return_value=client))
    producer = outbox_relay.SnsFifoProducer(TOPIC, SUBSCRIPTION, QUEUE)
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
        TOPIC,
    )
    monkeypatch.setenv("PLATFORM_DOMAIN_EVENTS_SUBSCRIPTION_ARN", SUBSCRIPTION)
    monkeypatch.setenv("PLATFORM_DOMAIN_EVENTS_QUEUE_ARN", QUEUE)
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


@pytest.mark.asyncio
async def test_sns_publisher_requires_live_approved_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    client.get_subscription_attributes.return_value = subscription_attributes()
    monkeypatch.setattr(outbox_relay.boto3, "client", Mock(return_value=client))
    producer = outbox_relay.SnsFifoProducer(TOPIC, SUBSCRIPTION, QUEUE)
    await producer.start()
    client.get_subscription_attributes.assert_called_once_with(SubscriptionArn=SUBSCRIPTION)

    for attribute, value in (
        ("Endpoint", "arn:aws:sqs:ap-south-1:123456789012:wrong.fifo"),
        ("FilterPolicy", json.dumps({"eventType": ["lead.created.v1"]})),
        ("RedrivePolicy", "{}"),
        ("RedrivePolicy", json.dumps({"deadLetterTargetArn": QUEUE})),
        ("PendingConfirmation", "true"),
    ):
        response = subscription_attributes()
        response["Attributes"][attribute] = value
        client.get_subscription_attributes.return_value = response
        with pytest.raises(ValueError, match="approved domain-event delivery path"):
            await producer.start()


@pytest.mark.asyncio
async def test_missing_subscription_stops_before_database_or_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = Mock(start=AsyncMock(side_effect=ValueError("subscription missing")), stop=AsyncMock())
    database = Mock()
    monkeypatch.setattr(outbox_relay, "get_settings", Mock(return_value=SimpleNamespace()))
    monkeypatch.setattr(outbox_relay, "make_producer", Mock(return_value=producer))
    monkeypatch.setattr(outbox_relay, "build_engine", database)
    with pytest.raises(ValueError, match="subscription missing"):
        await outbox_relay.run_once()
    database.assert_not_called()
    producer.stop.assert_not_awaited()
