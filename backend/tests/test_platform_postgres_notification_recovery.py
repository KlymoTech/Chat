"""Disposable PostgreSQL proof: claims, lease fencing, and crash recovery.

Set PLATFORM_TEST_POSTGRES_DSN to an isolated local/test PostgreSQL service.
Never runs against an unspecified or shared production database.
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.queue_notification_dispatch import (
    NotificationDispatcher, NotificationResult,
)
from northstar_api.modules.platform_runtime.queue_notification_persistence import (
    QueueAlertNotification,
)
from northstar_api.modules.platform_runtime.queue_notification_reconciliation import (
    NotificationLeaseReconciler,
)


@pytest.mark.asyncio
async def test_postgres_competing_claims_recovery_and_stale_acknowledgement():
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("disposable PostgreSQL qualification service unavailable")
    if not any(host in dsn for host in ("@localhost", "@127.0.0.1", "@postgres")):
        pytest.fail("refusing to mutate a nonlocal/shared PostgreSQL database")

    schema = "northstar_notification_qa_" + uuid4().hex
    base_url = dsn.replace("postgresql://", "postgresql+asyncpg://")
    admin = create_async_engine(base_url)
    isolated = None
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = create_async_engine(
            base_url,
            connect_args={"server_settings": {"search_path": f"{schema},public"}},
        )
        tenant, episode, notification_id = uuid4(), uuid4(), uuid4()
        now = datetime.now(UTC)
        async with isolated.begin() as conn:
            await conn.execute(text("CREATE TABLE tenants (id UUID PRIMARY KEY)"))
            await conn.execute(text(
                "CREATE TABLE platform_queue_alert_episodes (id UUID PRIMARY KEY)"
            ))
            await conn.run_sync(QueueAlertNotification.__table__.create)
            await conn.execute(
                text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant}
            )
            await conn.execute(
                text("INSERT INTO platform_queue_alert_episodes (id) VALUES (:id)"),
                {"id": episode},
            )
            await conn.execute(
                text(
                    "INSERT INTO platform_queue_alert_notifications "
                    "(id, tenant_id, episode_id, dedupe_key, channel, status, "
                    "attempts, created_at, next_attempt_at) "
                    "VALUES (:id, :tenant, :episode, 'qa:one', 'email', "
                    "'pending', 0, :now, :now)"
                ),
                {"id": notification_id, "tenant": tenant, "episode": episode, "now": now},
            )

        sessions = async_sessionmaker(isolated, expire_on_commit=False)
        class Transport:
            async def send(self, _claim):
                return NotificationResult(True, "ack")

        first = NotificationDispatcher(sessions, Transport(), lease_seconds=2)
        second = NotificationDispatcher(sessions, Transport(), lease_seconds=2)
        claims = await asyncio.wait_for(
            asyncio.gather(first.claim(), second.claim()), 10
        )
        winners = [c for c in claims if c is not None]
        assert len(winners) == 1
        stale = winners[0]
        assert stale.tenant_id == tenant

        # Simulate a worker crash and expired lease, without sending a message.
        async with sessions.begin() as session:
            row = await session.get(QueueAlertNotification, notification_id)
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

        recovery = NotificationLeaseReconciler(sessions)
        result = await recovery.reconcile_once(tenant_id=tenant)
        assert (result.retried, result.exhausted) == (1, 0)

        async with sessions.begin() as session:
            row = await session.get(QueueAlertNotification, notification_id)
            assert row.status == "retrying"
            assert row.lease_token is None
            row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)

        renewed = await second.claim()
        assert renewed is not None
        assert renewed.id == stale.id
        assert renewed.lease_token != stale.lease_token
        assert renewed.attempts == 2

        # Even if the former worker receives a late external acknowledgement,
        # it must not override the renewed lease.
        first.claim = lambda: asyncio.sleep(0, result=stale)
        assert await first.dispatch_one() is False
        async with sessions() as session:
            row = await session.scalar(
                select(QueueAlertNotification).where(
                    QueueAlertNotification.id == notification_id
                )
            )
            assert row.status == "leased"
            assert row.lease_token == renewed.lease_token
            assert row.provider_reference is None

        second.claim = lambda: asyncio.sleep(0, result=renewed)
        assert await second.dispatch_one() is True
        async with sessions() as session:
            row = await session.get(QueueAlertNotification, notification_id)
            assert row.status == "delivered"
            assert row.provider_reference == "ack"
            assert row.attempts == 2
    finally:
        if isolated is not None:
            await isolated.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
