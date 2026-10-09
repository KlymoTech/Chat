"""Expired notification claim reconciliation is bounded and fail-closed."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from northstar_api.modules.platform_runtime.queue_notification_reconciliation import (
    NotificationLeaseReconciler, ReconciliationResult,
)


def session_factory(rows):
    session = MagicMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock()
    transaction = session.begin.return_value
    transaction.__aenter__ = AsyncMock()
    transaction.__aexit__ = AsyncMock()
    return MagicMock(return_value=session), session


def lease(attempts):
    return SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), status="leased", attempts=attempts,
        lease_token=uuid4(), lease_expires_at=datetime.now(UTC) - timedelta(seconds=2),
        delivered_at=None, provider_reference=None,
    )


@pytest.mark.asyncio
async def test_expired_claims_retry_or_exhaust_without_erasing_history():
    retry = lease(2)
    exhausted = lease(8)
    exhausted.provider_reference = "historical-receipt"
    sessions, session = session_factory([retry, exhausted])
    result = await NotificationLeaseReconciler(sessions, max_attempts=8).reconcile_once()
    assert result == ReconciliationResult(retried=1, exhausted=1)
    assert retry.status == "retrying"
    assert exhausted.status == "exhausted"
    assert retry.lease_token is None and exhausted.lease_expires_at is None
    assert exhausted.provider_reference == "historical-receipt"
    assert retry.attempts == 2 and exhausted.attempts == 8
    statement = session.scalars.await_args.args[0]
    assert "FOR UPDATE" in str(statement)
    assert "lease_expires_at" in str(statement)


@pytest.mark.asyncio
async def test_empty_queue_does_not_change_records():
    sessions, _ = session_factory([])
    result = await NotificationLeaseReconciler(sessions).reconcile_once()
    assert result == ReconciliationResult()


@pytest.mark.asyncio
async def test_tenant_filter_is_explicit():
    sessions, session = session_factory([])
    tenant = uuid4()
    await NotificationLeaseReconciler(sessions).reconcile_once(tenant_id=tenant)
    assert tenant in session.scalars.await_args.args[0].compile().params.values()


@pytest.mark.parametrize("kwargs", [
    {"max_attempts": 0}, {"batch_size": 0}, {"batch_size": 1001},
])
def test_limits_rejected(kwargs):
    with pytest.raises(ValueError):
        NotificationLeaseReconciler(MagicMock(), **kwargs)
