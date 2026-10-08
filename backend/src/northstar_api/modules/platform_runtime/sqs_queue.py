"""Amazon SQS publisher adapter for jobs already committed to PostgreSQL.

No queue is created here; deployment/IaC owns the queue and its redrive policy.
The caller must reconcile ambiguous send results before marking work dispatched.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .queue_contract import DeliveryOutcome, DispatchReceipt, DurableJob


class SqsQueuePublisher:
    def __init__(
        self, *,
        queue_url: str,
        client: Any,
        fifo: bool = False,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not queue_url.startswith("https://") or " " in queue_url:
            raise ValueError("SQS queue URL must be an HTTPS URL")
        if fifo != queue_url.endswith(".fifo"):
            raise ValueError("SQS FIFO setting must match queue URL")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._queue_url = queue_url
        self._client = client
        self._fifo = fifo
        self._timeout = timeout_seconds

    def _message(self, job: DurableJob) -> dict[str, Any]:
        body = json.dumps({
            "schemaVersion": 1,
            "jobId": str(job.job_id),
            "tenantId": str(job.tenant_id),
            "kind": job.kind,
            "payloadReference": job.payload_reference,
            "idempotencyKey": job.idempotency_key,
        }, sort_keys=True, separators=(",", ":"))
        if len(body.encode("utf-8")) > 256 * 1024:
            raise ValueError("SQS payload exceeds conservative message size limit")
        request: dict[str, Any] = {"QueueUrl": self._queue_url, "MessageBody": body}
        if self._fifo:
            request["MessageGroupId"] = str(job.tenant_id)
            request["MessageDeduplicationId"] = str(job.job_id)
        return request

    async def publish(self, job: DurableJob) -> DispatchReceipt:
        request = self._message(job)
        try:
            # boto3 is synchronous; never block the request/event loop.
            result = await asyncio.wait_for(
                asyncio.to_thread(self._client.send_message, **request),
                timeout=self._timeout,
            )
        except (TimeoutError, BotoCoreError, ClientError, OSError):
            # Timeout is ambiguous: broker may have accepted the message.
            # Dispatcher must retry idempotently; do not mark accepted as failed.
            return DispatchReceipt(job.job_id, DeliveryOutcome.RETRYABLE, "sqs")
        message_id = result.get("MessageId") if isinstance(result, dict) else None
        if not isinstance(message_id, str) or not message_id:
            return DispatchReceipt(job.job_id, DeliveryOutcome.RETRYABLE, "sqs")
        return DispatchReceipt(job.job_id, DeliveryOutcome.PUBLISHED, "sqs", message_id)
