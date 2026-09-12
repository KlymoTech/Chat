from __future__ import annotations

import asyncio
import re
import signal
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine, set_tenant_context
from northstar_api.lead_crm.connection_context import load_connection_context
from northstar_api.lead_crm.connectors import CRMError, crm_registry
from northstar_api.lead_crm.domain import CRMConnectionStatus, NormalizedCRMErrorCode
from northstar_api.lead_crm.models import CRMConnection, IntegrationHealthSnapshot
from northstar_api.logging import configure_logging

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)

HEALTH_INTERVAL_SECONDS = 300
HEALTH_BATCH_SIZE = 50
_ELIGIBLE_STATUSES = frozenset(
    {
        CRMConnectionStatus.CONNECTING.value,
        CRMConnectionStatus.HEALTHY.value,
        CRMConnectionStatus.DEGRADED.value,
        CRMConnectionStatus.UNHEALTHY.value,
        CRMConnectionStatus.AUTH_REQUIRED.value,
        CRMConnectionStatus.RATE_LIMITED.value,
        CRMConnectionStatus.CONFIGURATION_ERROR.value,
    }
)
_SENSITIVE_CHECK_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "refreshtoken",
    "secret",
    "token",
}


def _sensitive_check_key(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return any(normalized == key or normalized.endswith(key) for key in _SENSITIVE_CHECK_KEYS)


def _safe_checks(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, str] = {}
    for key, item in value.items():
        label = str(key)[:80]
        safe[label] = "[REDACTED]" if _sensitive_check_key(label) else str(item)[:160]
    return safe


def _crm_error_status(error: CRMError) -> str:
    if error.requires_reconnect or error.code == NormalizedCRMErrorCode.AUTHENTICATION_ERROR:
        return CRMConnectionStatus.AUTH_REQUIRED.value
    if error.code == NormalizedCRMErrorCode.RATE_LIMIT_ERROR:
        return CRMConnectionStatus.RATE_LIMITED.value
    if error.code == NormalizedCRMErrorCode.CONFIGURATION_ERROR:
        return CRMConnectionStatus.CONFIGURATION_ERROR.value
    return CRMConnectionStatus.UNHEALTHY.value


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _is_due(connection: CRMConnection, *, now: datetime) -> bool:
    if connection.status not in _ELIGIBLE_STATUSES:
        return False
    if connection.last_health_at is None:
        return True
    cutoff = now - timedelta(seconds=HEALTH_INTERVAL_SECONDS)
    return _aware(connection.last_health_at) <= cutoff


def _add_snapshot(
    session: AsyncSession,
    *,
    connection: CRMConnection,
    status: str,
    checks: dict[str, str],
    latency_ms: int | None,
    checked_at: datetime,
) -> None:
    session.add(
        IntegrationHealthSnapshot(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            status=status[:40],
            checks_json=checks,
            latency_ms=latency_ms,
            checked_at=checked_at,
        )
    )


async def _due_connections(session: AsyncSession, *, now: datetime) -> list[tuple[UUID, UUID]]:
    cutoff = now - timedelta(seconds=HEALTH_INTERVAL_SECONDS)
    rows = list(
        await session.execute(
            select(CRMConnection.id, CRMConnection.tenant_id)
            .where(
                CRMConnection.status.in_(_ELIGIBLE_STATUSES),
                or_(CRMConnection.last_health_at.is_(None), CRMConnection.last_health_at <= cutoff),
            )
            .order_by(CRMConnection.last_health_at.asc().nullsfirst(), CRMConnection.id)
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
    """Record one due CRM connection health snapshot.

    The connection row is locked before checking due state so multiple monitor
    replicas cannot create duplicate snapshots for the same interval.
    """

    checked_at = now or datetime.now(UTC)
    async with factory() as session:
        await set_tenant_context(session, tenant_id)
        connection = await session.scalar(
            select(CRMConnection)
            .where(CRMConnection.id == connection_id, CRMConnection.tenant_id == tenant_id)
            .with_for_update()
        )
        if connection is None or not _is_due(connection, now=checked_at):
            await session.commit()
            return False

        try:
            connection, context = await load_connection_context(
                session,
                tenant_id=tenant_id,
                connection_id=connection_id,
            )
            connector = crm_registry.get(context.provider)
            result = await connector.health_check(context)
            status = result.status.value
            connection.status = status
            connection.last_health_at = checked_at
            connection.last_error = (
                None
                if status == CRMConnectionStatus.HEALTHY.value
                else f"Scheduled health check reported {status}"[:1000]
            )
            _add_snapshot(
                session,
                connection=connection,
                status=status,
                checks=_safe_checks(result.checks),
                latency_ms=result.latency_ms,
                checked_at=checked_at,
            )
        except CRMError as exc:
            connection = await session.scalar(
                select(CRMConnection).where(
                    CRMConnection.id == connection_id,
                    CRMConnection.tenant_id == tenant_id,
                )
            )
            if connection is None:
                await session.commit()
                return False
            status = _crm_error_status(exc)
            connection.status = status
            connection.last_health_at = checked_at
            connection.last_error = f"Scheduled health check failed: {exc.code.value}"[:1000]
            _add_snapshot(
                session,
                connection=connection,
                status=status,
                checks={"healthCheck": "failed", "errorCode": exc.code.value},
                latency_ms=None,
                checked_at=checked_at,
            )
        except ValueError:
            connection = await session.scalar(
                select(CRMConnection).where(
                    CRMConnection.id == connection_id,
                    CRMConnection.tenant_id == tenant_id,
                )
            )
            if connection is None:
                await session.commit()
                return False
            connection.status = CRMConnectionStatus.CONFIGURATION_ERROR.value
            connection.last_health_at = checked_at
            connection.last_error = "Scheduled health check failed: invalid provider configuration"
            _add_snapshot(
                session,
                connection=connection,
                status=CRMConnectionStatus.CONFIGURATION_ERROR.value,
                checks={"healthCheck": "failed", "errorCode": "configuration_error"},
                latency_ms=None,
                checked_at=checked_at,
            )

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
                "crm_health_monitor_connection_failed",
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
        "crm_health_monitor_started",
        interval_seconds=HEALTH_INTERVAL_SECONDS,
        batch_size=HEALTH_BATCH_SIZE,
    )
    try:
        while not stop.is_set():
            result = await run_once(factory)
            if result["due"] or result["failed"]:
                logger.info("crm_health_monitor_completed", **result)
            try:
                await asyncio.wait_for(stop.wait(), timeout=float(HEALTH_INTERVAL_SECONDS))
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
        logger.info("crm_health_monitor_stopped")


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
