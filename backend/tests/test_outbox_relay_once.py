from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from northstar_api.handlers.outbox_relay import BATCH_SIZE, event_envelope, publish_batch


def make_event() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        aggregate_type="conversation",
        aggregate_id=str(uuid4()),
        event_type="conversation.created.v1",
        occurred_at=datetime.now(UTC),
        payload={"safe": True},
        published_at=None,
        attempts=0,
        last_error=None,
    )


@pytest.mark.asyncio
async def test_one_shot_relay_publishes_bounded_batch_without_polling() -> None:
    events = [make_event() for _ in range(BATCH_SIZE)]
    session = Mock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: events))
    session.commit = AsyncMock()
    producer = Mock(send_and_wait=AsyncMock())

    assert await publish_batch(session, producer) == BATCH_SIZE
    assert producer.send_and_wait.await_count == BATCH_SIZE
    session.scalars.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert all(event.published_at is not None for event in events)
    assert producer.send_and_wait.await_args_list[0].args[1] == event_envelope(events[0])


@pytest.mark.asyncio
async def test_failed_publish_records_attempt_and_propagates_for_queue_retry() -> None:
    event = make_event()
    session = Mock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [event]))
    session.commit = AsyncMock()
    producer = Mock(send_and_wait=AsyncMock(side_effect=RuntimeError("broker unavailable")))

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await publish_batch(session, producer)
    assert event.published_at is None
    assert event.attempts == 1
    assert event.last_error == "RuntimeError"
    session.commit.assert_awaited_once()
