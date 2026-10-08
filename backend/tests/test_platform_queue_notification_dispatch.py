"""Notification dispatcher tests: claim, acknowledgement, retry, and fencing."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_dispatch import (
    NotificationClaim, NotificationDispatcher, NotificationResult,
)


def session_factory(row=None):
    session = MagicMock()
    session.scalar = AsyncMock(return_value=row)
    session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock()
    session.begin.return_value.__aenter__ = AsyncMock()
    session.begin.return_value.__aexit__ = AsyncMock()
    return MagicMock(return_value=session), session


def claim(attempts=1):
    return NotificationClaim(uuid4(), uuid4(), uuid4(), "email", uuid4(), attempts)


@pytest.mark.asyncio
async def test_empty_queue_does_not_call_provider():
    factory, _ = session_factory()
    transport = MagicMock(send=AsyncMock())
    dispatcher = NotificationDispatcher(factory, transport)
    assert not await dispatcher.dispatch_one()
    transport.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_requires_delivery_reference():
    factory, session = session_factory()
    item = claim()
    transport = MagicMock(send=AsyncMock(return_value=NotificationResult(True, "receipt-1")))
    dispatcher = NotificationDispatcher(factory, transport)
    dispatcher.claim = AsyncMock(return_value=item)
    assert await dispatcher.dispatch_one()
    values = session.execute.await_args.args[0].compile().params.values()
    assert "delivered" in values
    assert "receipt-1" in values


@pytest.mark.asyncio
async def test_uncertain_delivery_is_retryable():
    factory, session = session_factory()
    transport = MagicMock(send=AsyncMock(side_effect=TimeoutError()))
    dispatcher = NotificationDispatcher(factory, transport)
    dispatcher.claim = AsyncMock(return_value=claim())
    assert await dispatcher.dispatch_one()
    assert "retrying" in session.execute.await_args.args[0].compile().params.values()


@pytest.mark.asyncio
async def test_retry_limit_marks_exhausted():
    factory, session = session_factory()
    transport = MagicMock(send=AsyncMock(return_value=NotificationResult(False)))
    dispatcher = NotificationDispatcher(factory, transport, max_attempts=2)
    dispatcher.claim = AsyncMock(return_value=claim(attempts=2))
    await dispatcher.dispatch_one()
    assert "exhausted" in session.execute.await_args.args[0].compile().params.values()


@pytest.mark.asyncio
async def test_stale_worker_cannot_claim_success():
    factory, session = session_factory()
    session.execute.return_value.rowcount = 0
    dispatcher = NotificationDispatcher(
        factory, MagicMock(send=AsyncMock(return_value=NotificationResult(True, "ack"))),
    )
    dispatcher.claim = AsyncMock(return_value=claim())
    assert not await dispatcher.dispatch_one()
    where_sql = str(session.execute.await_args.args[0])
    assert "lease_token" in where_sql
    assert "lease_expires_at" in where_sql


def test_invalid_dispatch_limits():
    with pytest.raises(ValueError):
        NotificationDispatcher(MagicMock(), MagicMock(), max_attempts=0)
