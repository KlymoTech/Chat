"""Notification admission is tenant scoped, generation bound and idempotent."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_admission import admit_alert_notification


def fake_session(tenant, episode, generation, *, inserted=True):
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"
    session.scalar = AsyncMock(return_value=SimpleNamespace(
        id=episode, tenant_id=tenant, state="open", first_seen_at=generation,
    ))
    result = MagicMock()
    result.scalar_one_or_none.return_value = uuid4() if inserted else None
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_first_admission_and_repeat_are_distinct():
    tenant, episode, stamp = uuid4(), uuid4(), datetime.now(UTC)
    session = fake_session(tenant, episode, stamp)
    assert await admit_alert_notification(
        session, tenant_id=tenant, episode_id=episode,
        channel="email", episode_generation=stamp,
    )
    statement = session.execute.await_args.args[0]
    assert "ON CONFLICT" in str(statement.compile())
    assert tenant in statement.compile().params.values()
    session.execute.return_value.scalar_one_or_none.return_value = None
    assert not await admit_alert_notification(
        session, tenant_id=tenant, episode_id=episode,
        channel="email", episode_generation=stamp,
    )


@pytest.mark.asyncio
async def test_foreign_or_changed_episode_never_admitted():
    tenant, episode, stamp = uuid4(), uuid4(), datetime.now(UTC)
    session = fake_session(tenant, episode, stamp)
    session.scalar.return_value = None
    with pytest.raises(ValueError, match="episode"):
        await admit_alert_notification(
            session, tenant_id=tenant, episode_id=episode,
            channel="email", episode_generation=stamp,
        )
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_unsupported_channel_before_db():
    session = MagicMock()
    with pytest.raises(ValueError, match="channel"):
        await admit_alert_notification(
            session, tenant_id=uuid4(), episode_id=uuid4(),
            channel="sms", episode_generation=datetime.now(UTC),
        )
    session.scalar.assert_not_called()
