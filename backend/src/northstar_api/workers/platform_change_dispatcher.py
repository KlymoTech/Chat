from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime

import httpx
import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from northstar_api.config import get_settings
from northstar_api.database import build_engine
from northstar_api.logging import configure_logging
from northstar_api.models import OutboxEvent
from northstar_api.modules.platform_runtime import DeploymentDispatchEvent

PLATFORM_CHANGE_EVENT_TYPE = "platform.runtime.change.approved.v1"

settings = get_settings()
configure_logging(settings)
logger = structlog.get_logger(__name__)


async def dispatch_forever() -> None:
    """Deliver approved platform changes without depending on Kafka.

    The executor is an external, least-privilege deployment controller (for
    example Step Functions/GitOps). The event remains unpublished until the
    executor accepts it, so normal outbox retry semantics are preserved.
    """
    if not settings.platform_change_executor_url or not settings.platform_change_executor_token:
        raise RuntimeError("platform change executor is not configured")

    engine = build_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop.set)
        except NotImplementedError:
            pass

    token = settings.platform_change_executor_token.get_secret_value()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Northstar-Event-Type": PLATFORM_CHANGE_EVENT_TYPE,
    }
    timeout = httpx.Timeout(settings.platform_change_executor_timeout_seconds)
    logger.info("platform_change_dispatcher_started")
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            while not stop.is_set():
                dispatched = False
                async with factory() as session:
                    event = await session.scalar(
                        select(OutboxEvent)
                        .where(
                            OutboxEvent.event_type == PLATFORM_CHANGE_EVENT_TYPE,
                            OutboxEvent.published_at.is_(None),
                            OutboxEvent.attempts < settings.platform_change_executor_max_attempts,
                        )
                        .order_by(OutboxEvent.occurred_at)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if event is not None:
                        try:
                            payload = DeploymentDispatchEvent.model_validate(event.payload)
                            envelope = {
                                "eventId": str(event.id),
                                "eventType": PLATFORM_CHANGE_EVENT_TYPE,
                                "schemaVersion": 1,
                                "occurredAt": event.occurred_at.isoformat(),
                                "payload": payload.model_dump(by_alias=True, mode="json"),
                            }
                            response = await client.post(
                                settings.platform_change_executor_url,
                                json=envelope,
                                headers={**headers, "Idempotency-Key": str(event.id)},
                            )
                            response.raise_for_status()
                            event.published_at = datetime.now(UTC)
                            event.last_error = None
                            dispatched = True
                            logger.info(
                                "platform_change_dispatched",
                                event_id=str(event.id),
                                change_id=str(payload.change_id),
                                environment=payload.environment,
                            )
                        except (httpx.HTTPError, ValidationError) as exc:
                            event.attempts += 1
                            event.last_error = type(exc).__name__[:500]
                            logger.warning(
                                "platform_change_dispatch_failed",
                                event_id=str(event.id),
                                attempts=event.attempts,
                                error=type(exc).__name__,
                            )
                        await session.commit()
                if not dispatched:
                    try:
                        await asyncio.wait_for(
                            stop.wait(),
                            timeout=settings.platform_change_executor_poll_seconds,
                        )
                    except TimeoutError:
                        pass
    finally:
        await engine.dispose()
        logger.info("platform_change_dispatcher_stopped")


def main() -> None:
    if not settings.platform_change_executor_url or not settings.platform_change_executor_token:
        raise SystemExit(
            "PLATFORM_CHANGE_EXECUTOR_URL and PLATFORM_CHANGE_EXECUTOR_TOKEN are required"
        )
    asyncio.run(dispatch_forever())


if __name__ == "__main__":
    main()
