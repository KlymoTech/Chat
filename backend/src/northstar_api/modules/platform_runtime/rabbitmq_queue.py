"""RabbitMQ publisher with mandatory routing and broker confirms.

Runs only against a provisioned durable exchange/queue. The caller must
persist job admission before invoking this adapter. Ambiguous publish outcomes
are retryable, and workers must be idempotent.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from amqp import Message

from .queue_contract import DeliveryOutcome, DispatchReceipt, DurableJob


class RabbitMqQueuePublisher:
    def __init__(
        self,
        *,
        channel: Any,
        exchange: str = "app.jobs.v1",
        routing_key: str = "platform.durable",
        timeout_seconds: float = 10.0,
    ) -> None:
        if not exchange or not routing_key or timeout_seconds <= 0:
            raise ValueError("exchange, routing key and positive timeout required")
        self._channel = channel
        self._exchange = exchange
        self._routing_key = routing_key
        self._timeout = timeout_seconds

    def _publish_sync(self, job: DurableJob) -> bool:
        # py-amqp channel confirm_select enables synchronous publisher
        # acknowledgements; basic_publish returns the broker confirm result.
        # Mandatory routing additionally rejects unroutable publications.
        body = json.dumps(
            {
                "schemaVersion": 1,
                "jobId": str(job.job_id),
                "tenantId": str(job.tenant_id),
                "kind": job.kind,
                "payloadReference": job.payload_reference,
                "idempotencyKey": job.idempotency_key,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self._channel.confirm_select()
        message = Message(
            body=body,
            delivery_mode=2,
            content_type="application/json",
            message_id=str(job.job_id),
            headers={"schemaVersion": 1},
        )
        result = self._channel.basic_publish(
            message,
            exchange=self._exchange,
            routing_key=self._routing_key,
            mandatory=True,
        )
        return result is True

    async def publish(self, job: DurableJob) -> DispatchReceipt:
        try:
            confirmed = await asyncio.wait_for(
                asyncio.to_thread(self._publish_sync, job),
                timeout=self._timeout,
            )
        except Exception:
            # An acknowledgement can be lost even after broker acceptance.
            # Do not claim success or discard authoritative durable job state.
            return DispatchReceipt(job.job_id, DeliveryOutcome.RETRYABLE, "rabbitmq")
        if not confirmed:
            return DispatchReceipt(job.job_id, DeliveryOutcome.RETRYABLE, "rabbitmq")
        return DispatchReceipt(job.job_id, DeliveryOutcome.PUBLISHED, "rabbitmq", str(job.job_id))
