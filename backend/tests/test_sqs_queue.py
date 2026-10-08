"""SQS adapter tests use an injected fake client; no AWS credentials required."""
import json
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError

from northstar_api.modules.platform_runtime.queue_contract import (
    DeliveryOutcome,
    DurableJob,
    dispatch_committed_job,
)
from northstar_api.modules.platform_runtime.sqs_queue import SqsQueuePublisher


def make_job() -> DurableJob:
    return DurableJob(uuid4(), uuid4(), "knowledge.index", "db:source:123", "request-0001")


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_standard_queue_publishes_minimal_pointer_message():
    client = FakeClient({"MessageId": "msg-123"})
    job = make_job()
    adapter = SqsQueuePublisher(queue_url="https://sqs.us-east-1.amazonaws.com/123/jobs", client=client)
    receipt = await dispatch_committed_job(adapter, job)
    assert receipt.outcome is DeliveryOutcome.PUBLISHED
    assert receipt.reference == "msg-123"
    payload = json.loads(client.calls[0]["MessageBody"])
    assert payload["tenantId"] == str(job.tenant_id)
    assert payload["payloadReference"] == job.payload_reference
    assert "MessageGroupId" not in client.calls[0]


@pytest.mark.asyncio
async def test_fifo_queue_enforces_tenant_group_and_job_dedup():
    client = FakeClient({"MessageId": "fifo-msg"})
    job = make_job()
    adapter = SqsQueuePublisher(queue_url="https://sqs.us-east-1.amazonaws.com/123/jobs.fifo",
                                client=client, fifo=True)
    await adapter.publish(job)
    assert client.calls[0]["MessageGroupId"] == str(job.tenant_id)
    assert client.calls[0]["MessageDeduplicationId"] == str(job.job_id)


@pytest.mark.asyncio
async def test_missing_acknowledgement_is_retryable():
    adapter = SqsQueuePublisher(queue_url="https://sqs.us-east-1.amazonaws.com/123/jobs",
                                client=FakeClient({}))
    assert (await adapter.publish(make_job())).outcome is DeliveryOutcome.RETRYABLE


@pytest.mark.asyncio
async def test_provider_failure_is_retryable_not_false_success():
    error = ClientError({"Error": {"Code": "ThrottlingException", "Message": "throttled"}},
                        "SendMessage")
    adapter = SqsQueuePublisher(queue_url="https://sqs.us-east-1.amazonaws.com/123/jobs",
                                client=FakeClient(error=error))
    assert (await adapter.publish(make_job())).outcome is DeliveryOutcome.RETRYABLE


def test_invalid_queue_configuration_rejected():
    with pytest.raises(ValueError):
        SqsQueuePublisher(queue_url="http://not-secure", client=FakeClient())
    with pytest.raises(ValueError):
        SqsQueuePublisher(queue_url="https://sqs.us-east-1.amazonaws.com/123/jobs.fifo",
                          client=FakeClient(), fifo=False)
