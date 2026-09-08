from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.lead_crm.circuit import record_failure, record_success
from northstar_api.lead_crm.connectors import CRMConnectionContext, CRMError, crm_registry
from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store
from northstar_api.lead_crm.domain import CRMDeliveryStatus, CRMProvider, NormalizedCRMErrorCode
from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, LeadActivityEvent
from northstar_api.logging import configure_logging
from northstar_api.services.outbox import enqueue_event

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)

STALE_PROCESSING_AGE = timedelta(minutes=10)
RECONCILE_BATCH = 50


async def _context(connection: CRMConnection) -> CRMConnectionContext:
    credentials: dict[str, Any] = {}
    if connection.credentials_encrypted:
        try:
            credentials = credential_store.decrypt(connection.credentials_encrypted)
        except CredentialStoreError as exc:
            raise CRMError(
                NormalizedCRMErrorCode.AUTHENTICATION_ERROR,
                "Stored CRM credentials are unreadable",
                requires_reconnect=True,
            ) from exc
    return CRMConnectionContext(
        tenant_id=connection.tenant_id,
        connection_id=connection.id,
        provider=CRMProvider(connection.provider),
        configuration=dict(connection.configuration_json or {}),
        credentials=credentials,
    )


async def recover_stale_processing(session: AsyncSession, now: datetime) -> int:
    rows = list(
        await session.scalars(
            select(CRMDelivery)
            .where(
                CRMDelivery.status == CRMDeliveryStatus.PROCESSING.value,
                CRMDelivery.processing_at.is_not(None),
                CRMDelivery.processing_at <= now - STALE_PROCESSING_AGE,
            )
            .with_for_update(skip_locked=True)
            .limit(RECONCILE_BATCH)
        )
    )
    for delivery in rows:
        delivery.status = CRMDeliveryStatus.RETRYING.value
        delivery.next_retry_at = now
        delivery.last_error_code = "stale_processing_recovered"
        delivery.last_error_message = "Delivery worker stopped before processing completed"
        session.add(
            LeadActivityEvent(
                tenant_id=delivery.tenant_id,
                lead_id=delivery.lead_id,
                event_type="lead.crm.delivery.recovered.v1",
                correlation_id=delivery.correlation_id,
                details_json={"deliveryId": str(delivery.id), "previousStatus": "processing"},
            )
        )
    return len(rows)


async def reconcile_verified_records(session: AsyncSession) -> tuple[int, int]:
    rows = list(
        await session.scalars(
            select(CRMDelivery)
            .where(
                CRMDelivery.status.in_(
                    (CRMDeliveryStatus.ACKNOWLEDGED.value, CRMDeliveryStatus.VERIFYING.value)
                ),
                CRMDelivery.external_record_id.is_not(None),
            )
            .order_by(CRMDelivery.acknowledged_at)
            .with_for_update(skip_locked=True)
            .limit(RECONCILE_BATCH)
        )
    )
    verified = 0
    deferred = 0
    for delivery in rows:
        connection = await session.scalar(
            select(CRMConnection).where(
                CRMConnection.id == delivery.connection_id,
                CRMConnection.tenant_id == delivery.tenant_id,
            )
        )
        if connection is None or connection.status == "disabled":
            delivery.status = CRMDeliveryStatus.FAILED.value
            delivery.last_error_code = "connection_unavailable"
            delivery.last_error_message = "CRM connection is unavailable during reconciliation"
            continue
        connector = crm_registry.get(CRMProvider(connection.provider))
        if not connector.capabilities.read_back:
            delivery.status = CRMDeliveryStatus.VERIFIED.value
            delivery.verified_at = datetime.now(UTC)
            verified += 1
            continue
        context = await _context(connection)
        delivery.status = CRMDeliveryStatus.VERIFYING.value
        try:
            record = await connector.get_lead(context, str(delivery.external_record_id))
            provider_id = record.get("id")
            if provider_id is not None and str(provider_id) != delivery.external_record_id:
                raise CRMError(
                    NormalizedCRMErrorCode.VALIDATION_ERROR,
                    "CRM reconciliation returned a different record ID",
                )
            delivery.status = CRMDeliveryStatus.VERIFIED.value
            delivery.verified_at = datetime.now(UTC)
            delivery.last_error_code = None
            delivery.last_error_message = None
            connection.last_success_at = datetime.now(UTC)
            connection.last_error = None
            await record_success(
                session,
                tenant_id=delivery.tenant_id,
                connection_id=connection.id,
            )
            session.add(
                LeadActivityEvent(
                    tenant_id=delivery.tenant_id,
                    lead_id=delivery.lead_id,
                    event_type="lead.crm.delivery.verified.v1",
                    correlation_id=delivery.correlation_id,
                    details_json={
                        "deliveryId": str(delivery.id),
                        "provider": delivery.provider,
                        "externalRecordId": delivery.external_record_id,
                        "source": "reconciliation",
                    },
                )
            )
            enqueue_event(
                session,
                tenant_id=delivery.tenant_id,
                aggregate_type="crm_delivery",
                aggregate_id=delivery.id,
                event_type="lead.crm.delivery.verified.v1",
                payload={
                    "leadId": str(delivery.lead_id),
                    "deliveryId": str(delivery.id),
                    "externalRecordId": delivery.external_record_id,
                    "provider": delivery.provider,
                    "source": "reconciliation",
                },
            )
            verified += 1
        except CRMError as exc:
            connection.last_failure_at = datetime.now(UTC)
            connection.last_error = exc.code.value
            if exc.retryable:
                delivery.status = CRMDeliveryStatus.ACKNOWLEDGED.value
                delivery.last_error_code = exc.code.value
                delivery.last_error_message = "Read-back verification temporarily unavailable"
                deferred += 1
                await record_failure(
                    session,
                    tenant_id=delivery.tenant_id,
                    connection_id=connection.id,
                    threshold=5,
                    cooldown_seconds=60,
                )
            elif exc.requires_reconnect:
                delivery.status = CRMDeliveryStatus.AUTH_REQUIRED.value
                delivery.last_error_code = exc.code.value
                delivery.last_error_message = "CRM credentials require reconnection"
                connection.status = "auth_required"
            else:
                delivery.status = CRMDeliveryStatus.FAILED.value
                delivery.last_error_code = exc.code.value
                delivery.last_error_message = "CRM read-back verification failed"
    return verified, deferred


async def run_once(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    recovered = await recover_stale_processing(session, now)
    verified, deferred = await reconcile_verified_records(session)
    await session.commit()
    return {"recovered": recovered, "verified": verified, "deferred": deferred}


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
    logger.info("crm_reconciliation_worker_started")
    try:
        while not stop.is_set():
            try:
                async with factory() as session:
                    result = await run_once(session)
                if any(result.values()):
                    logger.info("crm_reconciliation_completed", **result)
            except Exception as exc:
                logger.exception("crm_reconciliation_failed", error=type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=30.0)
            except TimeoutError:
                pass
    finally:
        await engine.dispose()
        logger.info("crm_reconciliation_worker_stopped")


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
