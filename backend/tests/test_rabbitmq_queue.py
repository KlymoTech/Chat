"""RabbitMQ confirmation tests with a fake py-amqp channel."""
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_contract import (
    DeliveryOutcome,
    DurableJob,
    dispatch_committed_job,
)
from northstar_api.modules.platform_runtime.rabbitmq_queue import RabbitMqQueuePublisher


def job() -> DurableJob:
    return DurableJob(uuid4(), uuid4(), "knowledge.index", "db:source:1", "request-0001")


class Channel:
    def __init__(self, response=True, error=None):
        self.response = response
        self.error = error
        self.confirmed = False
        self.calls = []

    def confirm_select(self):
        self.confirmed = True

    def basic_publish(self, message, **options):
        self.calls.append((message, options))
        if self.error:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_confirmed_durable_mandatory_publication():
    channel = Channel()
    payload = job()
    publisher = RabbitMqQueuePublisher(channel=channel)
    receipt = await dispatch_committed_job(publisher, payload)
    assert channel.confirmed
    assert receipt.outcome is DeliveryOutcome.PUBLISHED
    assert receipt.reference == str(payload.job_id)
    message, options = channel.calls[0]
    assert options["mandatory"] is True
    assert options["exchange"] == "app.jobs.v1"
    assert message.properties["delivery_mode"] == 2
    assert message.properties["message_id"] == str(payload.job_id)


@pytest.mark.asyncio
async def test_missing_confirm_does_not_acknowledge_job():
    receipt = await RabbitMqQueuePublisher(channel=Channel(response=None)).publish(job())
    assert receipt.outcome is DeliveryOutcome.RETRYABLE


@pytest.mark.asyncio
async def test_transport_failure_keeps_job_retryable():
    receipt = await RabbitMqQueuePublisher(channel=Channel(error=OSError("connection lost"))).publish(job())
    assert receipt.outcome is DeliveryOutcome.RETRYABLE


def test_invalid_config_fails_fast():
    with pytest.raises(ValueError):
        RabbitMqQueuePublisher(channel=Channel(), exchange="")
