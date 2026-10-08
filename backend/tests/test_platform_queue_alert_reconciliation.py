"""Queue episode reconciliation unit contracts."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_alerts import QueueAlert
from northstar_api.modules.platform_runtime.queue_alert_reconciliation import reconcile_queue_alerts


def session_with(rows):
    session = MagicMock()
    records = MagicMock()
    records.all.return_value = rows
    session.scalars = AsyncMock(return_value=records)
    return session


@pytest.mark.asyncio
async def test_new_alert_creates_one_open_episode():
    session = session_with([])
    tenant = uuid4()
    alert = QueueAlert("queue_overdue", "warning", "tenant", 7, "threshold_exceeded")
    state = await reconcile_queue_alerts(
        session, tenant_id=tenant, alerts=(alert,), observed_at=datetime.now(UTC),
    )
    assert state == {"opened": 1, "updated": 0, "resolved": 0}
    episode = session.add.call_args.args[0]
    assert episode.tenant_id == tenant
    assert episode.state == "open"
    assert episode.occurrences == 1


@pytest.mark.asyncio
async def test_existing_episode_is_updated_without_duplication():
    tenant = uuid4()
    row = MagicMock(
        tenant_id=tenant, code="queue_overdue", state="open",
        severity="warning", occurrences=2,
    )
    session = session_with([row])
    alert = QueueAlert("queue_overdue", "critical", "tenant", 50, "threshold_exceeded")
    result = await reconcile_queue_alerts(
        session, tenant_id=tenant, alerts=(alert,), observed_at=datetime.now(UTC),
    )
    assert result == {"opened": 0, "updated": 1, "resolved": 0}
    assert row.severity == "critical"
    assert row.occurrences == 3
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_missing_alert_resolves_existing_episode():
    row = MagicMock(code="queue_overdue", state="open")
    session = session_with([row])
    now = datetime.now(UTC)
    result = await reconcile_queue_alerts(
        session, tenant_id=uuid4(), alerts=(), observed_at=now,
    )
    assert result["resolved"] == 1
    assert row.state == "resolved"
    assert row.resolved_at == now


@pytest.mark.asyncio
async def test_duplicate_observation_rejected_before_database_access():
    session = session_with([])
    alert = QueueAlert("queue_overdue", "warning", "tenant", 7, "threshold_exceeded")
    with pytest.raises(ValueError, match="duplicate"):
        await reconcile_queue_alerts(
            session, tenant_id=uuid4(), alerts=(alert, alert),
        )
    session.scalars.assert_not_awaited()
