"""Disposable PostgreSQL qualification for concurrent notification reconcilers.

Use only the explicitly configured local PostgreSQL test service. This test
does not contact notification providers or change application production data.
"""
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from northstar_api.modules.platform_runtime.queue_notification_dispatch import NotificationDispatcher, NotificationResult
from northstar_api.modules.platform_runtime.queue_notification_persistence import QueueAlertNotification
from northstar_api.modules.platform_runtime.queue_notification_reconciliation import NotificationLeaseReconciler


@pytest.mark.asyncio
async def test_concurrent_reconcilers_exhaustion_and_restart():
    dsn = os.environ.get("PLATFORM_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("disposable PostgreSQL qualification service unavailable")
    parsed = urlsplit(dsn.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.hostname not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("refusing to mutate a nonlocal PostgreSQL database")
    url = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "northstar_notification_recovery_" + uuid4().hex
    admin = create_async_engine(url)
    isolated = None
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = create_async_engine(
            url, connect_args={"server_settings": {"search_path": f"{schema},public"}}
        )
        tenant, episode, other_tenant = uuid4(), uuid4(), uuid4()
        retry_id, exhausted_id, active_id, foreign_id = (uuid4() for _ in range(4))
        now = datetime.now(UTC)
        async with isolated.begin() as conn:
            await conn.execute(text("CREATE TABLE tenants (id UUID PRIMARY KEY)"))
            await conn.execute(text("CREATE TABLE platform_queue_alert_episodes (id UUID PRIMARY KEY)"))
            await conn.run_sync(QueueAlertNotification.__table__.create)
            for tenant_id in (tenant, other_tenant):
                await conn.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant_id})
            await conn.execute(text("INSERT INTO platform_queue_alert_episodes (id) VALUES (:id)"), {"id": episode})
            for key, notification_id, owner, attempts, expires in (
                ("retry", retry_id, tenant, 2, now - timedelta(seconds=5)),
                ("exhaust", exhausted_id, tenant, 8, now - timedelta(seconds=5)),
                ("active", active_id, tenant, 1, now + timedelta(hours=1)),
                ("other", foreign_id, other_tenant, 1, now - timedelta(seconds=5)),
            ):
                await conn.execute(text(
                    "INSERT INTO platform_queue_alert_notifications "
                    "(id, tenant_id, episode_id, dedupe_key, channel, status, attempts, "
                    "created_at, next_attempt_at, lease_token, lease_expires_at) "
                    "VALUES (:id, :tenant, :episode, :key, 'webhook', 'leased', :attempts, "
                    ":now, :next, :token, :expiry)"
                ), {
                    "id": notification_id, "tenant": owner, "episode": episode,
                    "key": key, "attempts": attempts, "now": now,
                    "next": now + timedelta(hours=1) if key == "other" else now - timedelta(seconds=10),
                    "token": uuid4(),
                    "expiry": expires,
                })

        sessions = async_sessionmaker(isolated, expire_on_commit=False)
        first = NotificationLeaseReconciler(sessions, batch_size=2)
        second = NotificationLeaseReconciler(sessions, batch_size=2)
        outcomes = await asyncio.wait_for(asyncio.gather(
            first.reconcile_once(tenant_id=tenant),
            second.reconcile_once(tenant_id=tenant),
        ), timeout=15)
        assert sum(x.retried for x in outcomes) == 1
        assert sum(x.exhausted for x in outcomes) == 1
        async with sessions() as session:
            retry = await session.get(QueueAlertNotification, retry_id)
            exhausted = await session.get(QueueAlertNotification, exhausted_id)
            active = await session.get(QueueAlertNotification, active_id)
            foreign = await session.get(QueueAlertNotification, foreign_id)
            assert retry.status == "retrying" and retry.lease_token is None
            assert retry.attempts == 2
            assert exhausted.status == "exhausted" and exhausted.attempts == 8
            assert exhausted.lease_token is None
            assert active.status == "leased" and active.lease_token is not None
            assert foreign.status == "leased" and foreign.lease_token is not None

        # A fresh dispatcher instance after process restart can claim retry work.
        class Transport:
            async def send(self, _notification):
                return NotificationResult(True, "restart-receipt")

        restarted = NotificationDispatcher(sessions, Transport())
        item = await restarted.claim()
        assert item is not None and item.id == retry_id and item.attempts == 3
        # Use the persisted lease through a newly constructed worker object.
        restarted.claim = lambda: asyncio.sleep(0, result=item)
        assert await restarted.dispatch_one()
        async with sessions() as session:
            row = await session.scalar(select(QueueAlertNotification).where(
                QueueAlertNotification.id == retry_id
            ))
            assert row.status == "delivered"
            assert row.provider_reference == "restart-receipt"
            assert row.attempts == 3
    finally:
        if isolated is not None:
            await isolated.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
