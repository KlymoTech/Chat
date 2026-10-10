"""Provider-neutral durable queue admission contract.

The application must persist accepted work before publishing through any
broker. A broker receipt alone is never an authoritative job record.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from uuid import UUID


class QueueAdmissionError(RuntimeError):
    """No durable admission occurred; caller must not return 'accepted'."""


class DeliveryOutcome(str, Enum):
    PUBLISHED = "published"
    RETRYABLE = "retryable"
    REJECTED = "rejected"


@dataclass(frozen=True)
class DurableJob:
    job_id: UUID
    tenant_id: UUID
    kind: str
    payload_reference: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.kind or not self.payload_reference or len(self.idempotency_key) < 8:
            raise ValueError("job kind, payload reference and idempotency key are required")


@dataclass(frozen=True)
class DispatchReceipt:
    job_id: UUID
    outcome: DeliveryOutcome
    provider: str
    reference: str | None = None


class DurableJobStore(Protocol):
    async def accept(self, job: DurableJob) -> bool:
        """Commit admission idempotently; False means already admitted."""


class QueuePublisher(Protocol):
    async def publish(self, job: DurableJob) -> DispatchReceipt:
        """Publish previously committed work; never invent admission."""


async def accept_durable_job(store: DurableJobStore, job: DurableJob) -> bool:
    """Persist work without contacting a broker.

    Publishing belongs to the replayable dispatcher, not this transaction.
    If the database commit fails, the exception propagates to the caller.
    """
    return await store.accept(job)


async def dispatch_committed_job(publisher: QueuePublisher, job: DurableJob) -> DispatchReceipt:
    """Bound the publisher contract to the persisted job's identity."""
    receipt = await publisher.publish(job)
    if receipt.job_id != job.job_id:
        raise QueueAdmissionError("provider returned a receipt for another job")
    if receipt.outcome is DeliveryOutcome.PUBLISHED and not receipt.reference:
        raise QueueAdmissionError("provider acknowledged publication without a reference")
    return receipt
