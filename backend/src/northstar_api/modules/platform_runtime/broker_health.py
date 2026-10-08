"""Independent, read-only broker probes for the optional queue providers.

Do not use a successful database query as proof of broker health. These probes
must be configured with the same broker identity/queue as the publisher.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class BrokerProbe:
    provider: str
    status: str
    checked_at: str
    detail: str
    visible_messages: int | None = None
    inflight_messages: int | None = None

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def _result(provider: str, status: str, detail: str, visible: int | None = None,
            inflight: int | None = None) -> BrokerProbe:
    return BrokerProbe(
        provider=provider, status=status, checked_at=datetime.now(UTC).isoformat(),
        detail=detail, visible_messages=visible, inflight_messages=inflight,
    )


async def probe_sqs(client: Any, queue_url: str, *, timeout_seconds: float = 3.0) -> BrokerProbe:
    """Read SQS queue metadata without receiving/deleting or sending messages."""
    if not queue_url.startswith("https://") or timeout_seconds <= 0:
        raise ValueError("invalid SQS probe configuration")
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.get_queue_attributes,
                QueueUrl=queue_url,
                AttributeNames=[
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                ],
            ),
            timeout=timeout_seconds,
        )
        attributes = response["Attributes"]
        visible = int(attributes["ApproximateNumberOfMessages"])
        inflight = int(attributes["ApproximateNumberOfMessagesNotVisible"])
        if visible < 0 or inflight < 0:
            raise ValueError("negative queue depth")
        return _result("sqs", "healthy", "metadata_read_ok", visible, inflight)
    except (Exception):
        # Exceptions are intentionally not logged with URLs or credentials.
        return _result("sqs", "unavailable", "metadata_read_failed")


async def probe_rabbitmq(
    connection: Any,
    *,
    queue_name: str,
    timeout_seconds: float = 3.0,
) -> BrokerProbe:
    """Passively inspect an existing queue; never declare, consume or publish."""
    if not queue_name or timeout_seconds <= 0:
        raise ValueError("invalid RabbitMQ probe configuration")
    try:
        def inspect() -> tuple[int, int]:
            channel = connection.channel()
            try:
                reply = channel.queue_declare(queue=queue_name, passive=True)
                # py-amqp queue.declare_ok exposes message_count / consumer_count.
                depth = int(reply.message_count)
                consumers = int(reply.consumer_count)
                if depth < 0 or consumers < 0:
                    raise ValueError("invalid RabbitMQ queue counters")
                return depth, consumers
            finally:
                channel.close()

        depth, consumers = await asyncio.wait_for(asyncio.to_thread(inspect), timeout_seconds)
        return _result("rabbitmq", "healthy", f"passive_queue_read_ok_consumers_{consumers}", depth)
    except (Exception):
        return _result("rabbitmq", "unavailable", "passive_queue_read_failed")
