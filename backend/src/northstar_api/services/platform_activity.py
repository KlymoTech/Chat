"""Opt-in activity signal for the planned scale-to-zero scheduler."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import boto3
import structlog

from northstar_api.modules.platform_runtime.dynamodb_activity_marker import DynamoDbActivityMarker

logger = structlog.get_logger(__name__)


async def mark_platform_activity() -> bool:
    """Record activity with the workload role; never fail a completed request."""
    table = os.environ.get("PLATFORM_ACTIVITY_TABLE")
    key = os.environ.get("PLATFORM_ACTIVITY_KEY")
    if not table or not key:
        return False
    try:
        marker = DynamoDbActivityMarker(boto3.client("dynamodb"), table)
        await marker.mark_activity(key, at=datetime.now(UTC))
        return True
    except Exception as exc:
        logger.warning("platform_activity_marker_failed", error=type(exc).__name__)
        return False
