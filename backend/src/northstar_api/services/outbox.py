from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import boto3
import structlog
from botocore.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from northstar_api.models import OutboxEvent

logger = structlog.get_logger(__name__)
_OUTBOX_NUDGE_PENDING = "northstar_outbox_nudge_pending"
_AWS_SIGNAL_CONFIG = Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 1})


def send_outbox_nudge() -> bool:
    """Best-effort post-commit signal; scheduled recovery handles a lost signal."""
    queue_url = os.environ.get("PLATFORM_OUTBOX_NUDGE_QUEUE_URL")
    if not queue_url:
        return False
    try:
        table = os.environ.get("PLATFORM_ACTIVITY_TABLE")
        key = os.environ.get("PLATFORM_ACTIVITY_KEY")
        if table and key:
            try:
                boto3.client("dynamodb", config=_AWS_SIGNAL_CONFIG).update_item(
                    TableName=table,
                    Key={"activity_key": {"S": key}},
                    UpdateExpression="SET last_activity_epoch = :timestamp",
                    ConditionExpression=(
                        "attribute_not_exists(last_activity_epoch) OR last_activity_epoch <= :timestamp"
                    ),
                    ExpressionAttributeValues={
                        ":timestamp": {"N": str(int(datetime.now(UTC).timestamp()))}
                    },
                )
            except Exception as exc:
                logger.warning("outbox_activity_marker_failed", error=type(exc).__name__)
        boto3.client("sqs", config=_AWS_SIGNAL_CONFIG).send_message(
            QueueUrl=queue_url, MessageBody="outbox-nudge"
        )
        return True
    except Exception as exc:
        logger.warning("outbox_nudge_failed", error=type(exc).__name__)
        return False


@event.listens_for(AsyncSession.sync_session_class, "after_commit")
def _nudge_after_commit(session: Session) -> None:
    if session.info.pop(_OUTBOX_NUDGE_PENDING, False):
        send_outbox_nudge()


@event.listens_for(AsyncSession.sync_session_class, "after_rollback")
def _clear_nudge_after_rollback(session: Session) -> None:
    session.info.pop(_OUTBOX_NUDGE_PENDING, None)


def enqueue_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    aggregate_type: str,
    aggregate_id: str | UUID,
    event_type: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    event = OutboxEvent(
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    session.info[_OUTBOX_NUDGE_PENDING] = True
    return event
