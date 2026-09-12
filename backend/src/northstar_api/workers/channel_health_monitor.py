from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context
from northstar_api.lead_crm.channel_models import ChannelConnection
from northstar_api.lead_crm.channels import ChannelConnectionContext, channel_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.logging import configure_logging

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)

HEALTH_INTERVAL_SECONDS = 300
HEALTH_BATCH_SIZE = 50
_ELIGIBLE_STATUSES = frozenset(
    {
        "configured",
        "healthy",
        "degraded",
        "unhealthy",
        "auth_required",
        "rate_limited",
        "configuration_error",
        "unknown",
    }
)
_FAILURE_STATUSES = frozenset(
    {
        "degraded",
        "unhealthy",
        "auth_required",
        "rate_limited",
        "configuration_error",
    }
)
_KNOWN_HEALTH_STATUSES = _ELIGIBLE_STATUSES - {"configured"}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_due(connection: ChannelConnection, *, now: datetime) -> bool:
    if connection.status not in _ELIGIBLE_STATUSES:
        return False
    if connection.last_health_at is None:
        return True
    cutoff = now - timedelta(seconds=HEALTH_INTERVAL_SECONDS)
    return _aware(connection.last_health_at) <= cutoff


def _normalized_health_status(value: object) -> str:
    normalized = str(value or "unknown").strip().lower()[:40]
    return normalized if normalized in _KNOWN_HEALTH_STATUSES else "unknown"


def _context(connection: ChannelConnection, credentials: dict[str, Any]) -> ChannelConnectionContext:
    return ChannelConnectionContext(
        tenant_id=connection.tenant_id,
        connection_id=connection.id,
        provider=ChannelProvider(connection.provider),
        configuration=dict(connection.configuration_json or {}),
        credentials=dict(credentials),
    )


def _record_status(
    connection: ChannelConnection,
    *,
    status: str,
    checked_at: datetime,
    error_code: str | None = None,
) -> None:
    connection.status = status
    connection.last_health_at = checked_at
    if status == "healthy":
        connection.last_error = None
        return
    if status in _FAILURE_STATUSES:
        connection.last_failure_at = checked_at
    if error_code:
        connection.last_error = f"Scheduled channel health check failed: {error_code}"[:1000]
    else:
        connection.last_error = f"Scheduled channel health check reported {status}"[:1000]


async def _due_connections(session: AsyncSession, *, now: datetime) -> list[tuple[UUID, UUID]]:
    cutoff = now - timedelta(seconds=HEALTH_INTERVAL_SECONDS)
    rows = list(
        await session.execute(
            select(ChannelConnection.id, ChannelConnection.tenant_id)
            .where(
                ChannelConnection.status.in_(_ELIGIBLE_STATUSES),
                or_(ChannelConnection.last_health_at.is_(None), ChannelConnection.last_health_at <= cutoff),
            )
            .order_by(ChannelConnection.last_health_at.asc().nullsfirst(), ChannelConnection.id)
            .limit(HEALTH_BATCH_SIZE)
        )
    )
    return [(connection_id, tenant_id) for connection_id, tenant_id in rows]


async def monitor_connection(
    factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    connection_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Check one due channel connection using its existing connector contract."""

    checked_at = now or datetime.now(UTC)
    async with factory() as session:
        await set_tenant_context(session, tenant_id)
        connection = await session.scalar(
            select(ChannelConnection)
            .where(
                ChannelConnection.id == connection_id,
                ChannelConnection.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if connection is None or not _is_due(connection, now=checked_at):
            await session.commit()
            return False

        credentials: dict[str, Any] = {}
        if connection.credentials_encrypted:
            try:
                credentials = credential_store.decrypt(connection.credentials_encrypted)
            except CredentialStoreError:
                _record_status(
                    connection,
                    status="auth_required",
                    checked_at=checked_at,
                    error_code="credential_error",
                )
                await session.commit()
                return True

        try:
            context = _context(connection, credentials)
            connector = channel_registry.get(context.provider)
        except (KeyError, ValueError):
            _record_status(
                connection,
                status="configuration_error",
                checked_at=checked_at,
                error_code="configuration_error",
            )
            await session.commit()
            return True

        result = await connector.health_check(context)
        status = _normalized_health_status(result.get("status"))
        _record_status(connection, status=status, checked_at=checked_at)
        await session.commit()
        return True


async def run_once(factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    now = datetime.now(UTC)
    async with factory() as session:
        due = await _due_connections(session, now=now)

    checked = 0
    failed = 0
    for connection_id, tenant_id in due:
        try:
            if await monitor_connection(
                factory,
                tenant_id=tenant_id,
                connection_id=connection_id,
                now=now,
            ):
                checked += 1
        except Exception as exc:
            failed += 1
            logger.exception(
                "channel_health_monitor_connection_failed",
                connection_id=str(connection_id),
                tenant_id=str(tenant_id),
                error=type(exc).__name__,
            )
    return {"due": len(due), "checked": checked, "failed": failed}


async def run_forever() -> None:
    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass

    logger.info(
        "channel_health_monitor_started",
        interval_seconds=HEALTH_INTERVAL_SECONDS,
        batch_size=HEALTH_BATCH_SIZE,
    )
    try:
        while not stop.is_set():
            result = await run_once(factory)
            if result["due"] or result["failed"]:
                logger.info("channel_health_monitor_completed", **result)
            try:
                await asyncio.wait_for(stop.wait(), timeout=float(HEALTH_INTERVAL_SECONDS))
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
        logger.info("channel_health_monitor_stopped")


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
