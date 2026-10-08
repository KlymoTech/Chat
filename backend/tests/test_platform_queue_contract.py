"""Queue port contract: durable admission precedes provider publication."""
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_contract import (
    DeliveryOutcome,
    DispatchReceipt,
    DurableJob,
    QueueAdmissionError,
    accept_durable_job,
    dispatch_committed_job,
)


def job() -> DurableJob:
    return DurableJob(
        job_id=uuid4(), tenant_id=uuid4(), kind="knowledge.index",
        payload_reference="db:source:123", idempotency_key="request-0001",
    )


@pytest.mark.asyncio
async def test_admission_does_not_publish() -> None:
    class Store:
        calls = 0

        async def accept(self, value: DurableJob) -> bool:
            self.calls += 1
            return self.calls == 1

    store = Store()
    value = job()
    assert await accept_durable_job(store, value)
    assert not await accept_durable_job(store, value)
    assert store.calls == 2


@pytest.mark.asyncio
async def test_mismatched_provider_receipt_fails_closed() -> None:
    class Publisher:
        async def publish(self, value: DurableJob) -> DispatchReceipt:
            return DispatchReceipt(uuid4(), DeliveryOutcome.PUBLISHED, "sqs", "message-id")

    with pytest.raises(QueueAdmissionError, match="another job"):
        await dispatch_committed_job(Publisher(), job())


@pytest.mark.asyncio
async def test_missing_provider_receipt_reference_fails_closed() -> None:
    class Publisher:
        async def publish(self, value: DurableJob) -> DispatchReceipt:
            return DispatchReceipt(value.job_id, DeliveryOutcome.PUBLISHED, "rabbitmq")

    with pytest.raises(QueueAdmissionError, match="without a reference"):
        await dispatch_committed_job(Publisher(), job())


@pytest.mark.asyncio
async def test_publish_outcome_preserved_for_dispatcher_retry() -> None:
    class Publisher:
        async def publish(self, value: DurableJob) -> DispatchReceipt:
            return DispatchReceipt(value.job_id, DeliveryOutcome.RETRYABLE, "sqs")

    receipt = await dispatch_committed_job(Publisher(), job())
    assert receipt.outcome is DeliveryOutcome.RETRYABLE


def test_invalid_job_cannot_be_admitted() -> None:
    with pytest.raises(ValueError):
        DurableJob(uuid4(), uuid4(), "knowledge.index", "", "request-0001")
