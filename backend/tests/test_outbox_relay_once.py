from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.handlers.outbox_relay import BATCH_SIZE, event_envelope, publish_batch
from northstar_api.services import outbox


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


def test_outbox_nudge_only_after_commit_and_once_per_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    send = Mock(return_value=True)
    monkeypatch.setattr(outbox, "send_outbox_nudge", send)
    session = SimpleNamespace(info={outbox._OUTBOX_NUDGE_PENDING: True})

    outbox._nudge_after_commit(session)
    outbox._nudge_after_commit(session)
    send.assert_called_once()
    assert session.info == {}


def test_rollback_clears_outbox_nudge(monkeypatch: pytest.MonkeyPatch) -> None:
    send = Mock(return_value=True)
    monkeypatch.setattr(outbox, "send_outbox_nudge", send)
    session = SimpleNamespace(info={outbox._OUTBOX_NUDGE_PENDING: True})

    outbox._clear_nudge_after_rollback(session)
    outbox._nudge_after_commit(session)
    send.assert_not_called()


def test_opt_in_nudge_marks_activity_and_sends_one_sqs_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLATFORM_OUTBOX_NUDGE_QUEUE_URL", "https://sqs.example/queue")
    monkeypatch.setenv("PLATFORM_ACTIVITY_TABLE", "activity")
    monkeypatch.setenv("PLATFORM_ACTIVITY_KEY", "northstar:test")
    dynamo = Mock()
    sqs = Mock()
    monkeypatch.setattr(
        outbox.boto3, "client", lambda kind, **kwargs: {"dynamodb": dynamo, "sqs": sqs}[kind]
    )

    assert outbox.send_outbox_nudge() is True
    dynamo.update_item.assert_called_once()
    sqs.send_message.assert_called_once_with(
        QueueUrl="https://sqs.example/queue", MessageBody="outbox-nudge"
    )


def test_unconfigured_nudge_never_contacts_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLATFORM_OUTBOX_NUDGE_QUEUE_URL", raising=False)
    client = Mock()
    monkeypatch.setattr(outbox.boto3, "client", client)
    assert outbox.send_outbox_nudge() is False
    client.assert_not_called()


@pytest.mark.asyncio
async def test_sqlalchemy_hooks_only_nudge_committed_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nudge = Mock(return_value=True)
    monkeypatch.setattr(outbox, "send_outbox_nudge", nudge)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine)
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
            session.info[outbox._OUTBOX_NUDGE_PENDING] = True
            await session.rollback()
            await session.execute(text("SELECT 1"))
            await session.commit()
            nudge.assert_not_called()

            await session.execute(text("SELECT 1"))
            session.info[outbox._OUTBOX_NUDGE_PENDING] = True
            await session.commit()
            nudge.assert_called_once()
    finally:
        await engine.dispose()
