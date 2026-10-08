"""Dispatch lease outcomes: empty queue, retries, and bounded attempts."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_contract import (
    DeliveryOutcome, DispatchReceipt,
)
from northstar_api.modules.platform_runtime.queue_dispatch import (
    ClaimedJob, DurableDispatchService,
)
from northstar_api.modules.platform_runtime.queue_contract import DurableJob


def sessions():
    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock()
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock()
    transaction.__aexit__ = AsyncMock()
    session.begin.return_value = transaction
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock()
    factory = MagicMock(return_value=session)
    return factory, session


@pytest.mark.asyncio
async def test_claim_on_empty_queue_is_noop():
    factory, session = sessions()
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    service = DurableDispatchService(factory, publisher)
    assert await service.dispatch_one() is False
    publisher.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_confirmation_persists_ack():
    factory, session = sessions()
    job = DurableJob(uuid4(), uuid4(), "knowledge.index", "db:source:1", "request-0001")
    pub = MagicMock()
    pub.publish = AsyncMock(return_value=DispatchReceipt(job.job_id, DeliveryOutcome.PUBLISHED, "sqs", "message-1"))
    service = DurableDispatchService(factory, pub)
    service.claim = AsyncMock(return_value=ClaimedJob(job, uuid4(), 1))
    assert await service.dispatch_one() is True
    session.execute.assert_awaited_once()
    statement = session.execute.call_args.args[0]
    compiled = statement.compile()
    assert "published" in str(compiled.params.values())
    pub.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_ambiguous_publish_remains_retryable():
    factory, session = sessions()
    job = DurableJob(uuid4(), uuid4(), "knowledge.index", "db:source:1", "request-0001")
    pub = MagicMock()
    pub.publish = AsyncMock(side_effect=TimeoutError())
    service = DurableDispatchService(factory, pub)
    service.claim = AsyncMock(return_value=ClaimedJob(job, uuid4(), 1))
    await service.dispatch_one()
    statement = session.execute.call_args.args[0]
    assert "retrying" in str(statement.compile().params.values())


def test_invalid_lease_configuration_fails_fast():
    factory, _ = sessions()
    with pytest.raises(ValueError):
        DurableDispatchService(factory, MagicMock(), lease_seconds=0)
